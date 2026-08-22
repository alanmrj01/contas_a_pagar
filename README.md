# Contas a Pagar Web 2.0.2.0

Versão web do Contas a Pagar. O núcleo determinístico de leitura, detecção de layout, normalização, classificação, reconciliação e métricas permanece preservado. Esta edição acrescenta autenticação Supabase, persistência cifrada da BASE DADOS e os refinamentos de relatório explicitamente aprovados.

## Fluxo funcional preservado
1. Adicionar um ou mais arquivos financeiros (`.xlsx`, `.xls`, `.xlsm`, `.xlsb`).
2. Validar os arquivos com o mesmo motor determinístico da versão de referência.
3. Gerar o relatório. A aba atual navega para o relatório com os mesmos temas, filtros, gráficos, cards, cálculos e exportações.

A BASE DADOS continua separada e pode ser consultada, editada, exportada, substituída ou complementada. Alterações confirmadas são cifradas com AES-256-GCM e persistidas por usuário no Supabase.

## Segurança da edição web

### Sessão autenticada e temporária
- A tela inicial exige e-mail completo e senha validados pelo Supabase Auth; a senha não é armazenada pela aplicação.
- Depois do Auth, o servidor consulta `public.usuarios_autorizados` pela chave `user_id` e só libera usuários ativos com perfil `administrador` ou `basico`.
- Cada navegador recebe um token de sessão criptograficamente aleatório em cookie `HttpOnly`, `Secure` em HTTPS e `SameSite=Strict`.
- O token bruto não é usado como nome de pasta; o servidor usa seu SHA-256 como identificador interno.
- O ID da sessão não aparece na URL.
- A sessão expira após **2 horas de inatividade** e seus arquivos/artefatos temporários são destruídos pela própria aplicação.

### Upload protegido
- Limite funcional: **200 MB por arquivo**.
- O navegador gera uma chave AES-256-GCM exclusiva para cada upload.
- Cada bloco da planilha é criptografado no navegador antes do envio.
- A chave AES é embrulhada com RSA-OAEP/SHA-256 usando uma chave RSA efêmera criada no startup do servidor.
- A chave privada RSA nunca é gravada no projeto, GitHub ou disco de sessão.
- O upload ocorre em blocos de 16 MB para evitar carregar uma planilha grande inteira na memória do navegador/servidor de uma só vez.
- Os blocos permanecem criptografados no armazenamento temporário.
- A planilha só é materializada em plaintext durante o período mínimo necessário para o motor Python processá-la e é removida em seguida.
- Arquivos Office são verificados quanto a estrutura, extensão suportada, tamanho, caminhos internos e expansão anormal antes de entrarem no motor.

HTTPS/TLS continua obrigatório na hospedagem. A criptografia de aplicação é uma camada adicional e não substitui TLS.

### Relatórios e artefatos
- HTML, PDF e Excel não ficam em diretório público.
- Os artefatos são criptografados temporariamente em repouso com AES-256-GCM e chave exclusiva da sessão mantida somente em memória.
- `/report/current` e os downloads são entregues somente depois de o servidor validar a sessão correspondente.
- As respostas financeiras usam `Cache-Control: no-store`.
- A política CSP do relatório autoriza somente os hashes exatos dos scripts inline gerados pelo próprio relatório.

### Proteções adicionais
- CSRF token vinculado à sessão e validação de `Origin` para operações de escrita.
- CSP, HSTS em HTTPS, `X-Content-Type-Options`, proteção contra framing, política restritiva de permissões e `Referrer-Policy`.
- Limitador antiabuso deliberadamente generoso; não existe limite de relatórios por hora e o uso normal repetido não é restringido.
- Processamentos pesados são serializados por padrão para reduzir risco de exaustão de RAM, sem limitar quantas vezes o usuário pode executar o fluxo.
- Mensagens de erro são sanitizadas para não expor caminhos internos.
- O servidor não registra conteúdo das planilhas, fornecedores, valores ou dados do relatório por código da aplicação.
- Chaves de sessão e criptografia são efêmeras e não devem ser adicionadas ao GitHub.

Mais detalhes: `docs/SEGURANCA_WEB_2.0.2.md`.

## Desempenho do relatório
Depois de o motor gerar o HTML, uma etapa web de otimização mantém:
- reutilização de formatadores de moeda, percentual e data;
- índice de pesquisa pré-calculado por registro;
- cache dos termos pesquisados;
- debounce curto da pesquisa dinâmica;
- resize de layout limitado a um frame por ciclo do navegador;
- compressão HTTP para respostas textuais grandes.

Os cálculos permanecem determinísticos. As mudanças visuais ficam restritas aos gráficos, rótulos e controles solicitados nesta edição.

## Executar no Windows
Execute `run_web.bat`. O script cria `.venv`, instala `requirements.txt`, inicia o FastAPI e abre `http://127.0.0.1:8000`.

> Em HTTP local o cookie não usa a flag `Secure` para permitir desenvolvimento em `localhost`. Em produção HTTPS/Render ele é enviado como `Secure`.

## Render
O projeto já contém `render.yaml` e `start.sh`.

- Build: `pip install -r requirements.txt`
- Start: `sh start.sh`
- Health check: `/healthz`
- Um worker por padrão. Não aumente o número de workers/instâncias sem migrar o estado de sessão para um armazenamento compartilhado seguro ou adotar afinidade de sessão.

Autenticação e persistência exigem as variáveis secretas do Supabase e a chave de cifra da BASE DADOS. Consulte `docs/CONFIGURACAO_SUPABASE.md` e `.env.example`.

## Armazenamento
Por padrão, os dados temporários ficam em `runtime_data/`, que está ignorado pelo Git. Não use disco persistente para sessões financeiras temporárias sem uma revisão específica de segurança.

O filesystem efêmero do provedor não é usado como política de exclusão: a aplicação executa sua própria limpeza e expiração.

## Paridade com o motor original
`docs/CORE_PARITY_SHA256.json` registra os SHA-256 dos módulos críticos preservados da versão de referência, incluindo reconciliador, métricas, detector de layouts, normalização, PDF, Excel, base padrão e `app/report/report_template.html`.

## Testes
Instale `requirements-dev.txt` e execute:

```bash
pytest -q
```

A validação desta edição inclui compilação Python, sintaxe JavaScript, testes de criptografia/integridade, isolamento entre sessões, CSRF, limite de 200 MB, artefatos privados criptografados, expiração de sessão, geração HTML/PDF/Excel e paridade SHA-256 do núcleo protegido.

## Atenção antes de publicar o repositório
O projeto contém `resources/base_dados_padrao.xlsx`, porque ela faz parte da classificação determinística existente. Se essa base tiver informações internas da organização, o repositório deve permanecer **privado**.

A planilha em `samples/` desta entrega foi substituída por uma amostra sintética. Caso uma versão anterior com dados reais tenha sido enviada a um repositório público, apagar o arquivo em um commit novo não remove o conteúdo do histórico do Git; o histórico deve ser higienizado separadamente.

DataTech - AMRJ


## Refinos cirúrgicos — relatório e BASE DADOS

Esta edição mantém o motor determinístico e a arquitetura de segurança da 2.0.2 e altera somente os pontos aprovados:

- filtro visual **Pagamento/Mês**, usando pagamento no REALIZADO e Data prevista no PREVISTO;
- gráfico **Previsto x Realizado por categoria** comparando o mês de referência com o mês-calendário imediatamente anterior, ambos identificados pelo nome real do mês;
- visão mensal por fornecedor/Fluxo JMM/Categoria sem carga massiva de cards quando não existe filtro;
- rótulos dos cards usam o nome real do mês, sem a expressão genérica "mês mais recente";
- diagnóstico de fornecedores sem classificação segura na BASE DADOS durante a validação;
- base personalizada importada torna-se imediatamente ativa no front-end e no back-end da sessão, invalidando a validação anterior e exigindo nova validação;
- otimizações de execução dos filtros (cache de pesquisa, Sets de seleção, cache de facets e render agendado) sem mudar a lógica dos filtros.
