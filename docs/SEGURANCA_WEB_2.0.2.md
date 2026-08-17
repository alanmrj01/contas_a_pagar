# Arquitetura de Segurança — Contas a Pagar Web 2.0.2.0

## 1. Objetivo
Adicionar defesa em profundidade à edição web sem alterar o motor determinístico financeiro, o fluxo funcional ou o relatório visual aprovado.

## 2. Modelo de acesso
A ferramenta não implementa banco de usuários, cadastro ou senha. O acesso cria uma sessão anônima temporária. Isso isola os dados entre navegadores, mas não restringe quem pode abrir a URL pública. Caso a organização exija autorização por identidade, SSO/Entra/controle corporativo deve ser adicionado externamente no futuro, sem alterar a interface da aplicação.

## 3. Sessão
- Token aleatório: `secrets.token_urlsafe(32)`.
- Cookie: `HttpOnly`, `SameSite=Strict`, `Secure` quando a requisição chega por HTTPS, `Path=/`.
- O servidor indexa a sessão por SHA-256 do token.
- Nenhuma informação financeira é guardada no cookie.
- Nenhum ID de sessão é colocado na URL.
- Expiração: 7.200 segundos (2 horas) sem atividade.
- Ao expirar: estado validado, chave de artefatos, uploads e arquivos temporários da sessão são removidos.

## 4. Proteção de upload
Fluxo por arquivo:

1. O navegador gera AES-256-GCM.
2. O navegador recebe uma chave pública RSA 3072 bits efêmera do servidor.
3. A chave AES é embrulhada com RSA-OAEP/SHA-256.
4. A planilha é dividida em blocos (default: 16 MiB).
5. Cada bloco recebe IV aleatório de 96 bits e AAD contendo versão do protocolo, ID do upload, índice e tamanho em plaintext.
6. O servidor armazena somente ciphertext + IV até a validação.
7. Antes de chamar o motor financeiro, os blocos são autenticados/descriptografados para uma área de trabalho temporária.
8. O arquivo materializado é validado estruturalmente e utilizado pelo motor original.
9. Ao término da validação — com sucesso ou erro — a área plaintext e os blocos de upload são removidos.

A chave RSA privada existe apenas na memória do processo. Reiniciar o serviço invalida uploads em andamento, por desenho.

## 5. Validação de arquivos
Formatos funcionais preservados: `.xlsx`, `.xls`, `.xlsm`, `.xlsb`.

Controles adicionais:
- limite padrão de 200 MiB por arquivo;
- limite agregado de staging por sessão;
- validação de magic/estrutura Office;
- rejeição de ZIP Office protegido por senha;
- rejeição de caminhos internos suspeitos;
- quantidade máxima de componentes ZIP;
- limite de tamanho expandido;
- rejeição de taxa de compactação excepcional em componentes enormes.

O conteúdo recebido nunca é executado como código pela camada web. Arquivos `.xlsm` continuam sendo tratados como fonte de dados; macros não são executadas pelo servidor.

## 6. Dados durante o processamento
O motor Python validado precisa enxergar os dados em plaintext para interpretar Excel, strings, datas, fornecedores, regras de reconciliação, métricas e geração documental. Por isso esta arquitetura não promete computação sobre ciphertext.

O plaintext fica restrito ao processo/área temporária pelo menor período necessário. O `ValidatedInput` necessário para permitir geração/regeração do relatório permanece na memória da sessão até a expiração ou reinício do processo.

## 7. Relatório, PDF e Excel
Os arquivos produzidos pelo motor original são criados em staging privado e imediatamente convertidos para formato protegido:
- AES-256-GCM;
- chave de 256 bits exclusiva da sessão;
- chave somente em memória;
- chunks autenticados de 1 MiB;
- AAD vincula nome lógico, índice e tamanho do bloco.

Somente arquivos `.capenc` permanecem no armazenamento da sessão. O plaintext de staging é removido.

Os endpoints `/report/current` e `/report/<artefato>`:
1. resolvem a sessão pelo cookie;
2. localizam somente artefatos daquela sessão;
3. autenticam/descriptografam em streaming;
4. enviam o resultado ao navegador com `Cache-Control: no-store`.

## 8. BASE DADOS personalizada
A base personalizada é validada com as mesmas regras do motor existente. Depois da verificação, a estrutura `TableData` permanece somente na memória da sessão; não é mantida como arquivo plaintext persistente da sessão.

A base padrão necessária ao produto permanece no pacote do servidor, mas não possui rota pública de download.

## 9. CSRF e origem
Operações `POST/PUT/PATCH/DELETE` exigem:
- CSRF token derivado por HMAC da sessão;
- `Origin` compatível quando o navegador fornece o header;
- cookie `SameSite=Strict`.

O token CSRF é renovável a partir da sessão e não carrega dados financeiros.

## 10. Headers e cache
Respostas sensíveis:
- `Cache-Control: no-store, max-age=0`;
- `Pragma: no-cache`.

Camadas adicionais:
- `Content-Security-Policy`;
- `Strict-Transport-Security` em HTTPS;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`;
- `Permissions-Policy` restritiva;
- `Cross-Origin-Opener-Policy: same-origin`;
- `Cross-Origin-Resource-Policy: same-origin`.

Para o relatório, a CSP permite os scripts inline somente pelos SHA-256 exatos calculados após a geração. O CSS inline permanece permitido porque faz parte do relatório visual aprovado e não foi reescrito nesta alteração cirúrgica.

## 11. Antiabuso sem limitar o usuário
Não existe cota de relatórios/validações por hora. O limitador atual é de rajada e foi configurado deliberadamente acima de qualquer operação humana normal. O processamento pesado possui limite de concorrência para impedir múltiplos motores financeiros competindo por memória ao mesmo tempo; tarefas legítimas subsequentes aguardam e continuam.

## 12. Logs e erros
O código da aplicação não registra conteúdo de planilhas, valores financeiros, fornecedores ou relatório. Erros retornados ao cliente têm caminhos internos sanitizados.

Ainda assim, a configuração do provedor deve evitar ferramentas de observabilidade que capturem corpos de requisição/resposta sensíveis.

## 13. TLS e limites da proteção
HTTPS/TLS protege o trânsito entre navegador e infraestrutura. A criptografia AES antes do upload acrescenta uma camada na carga útil até o processo da aplicação. Isso **não** transforma a solução em criptografia ponta a ponta no sentido de um servidor incapaz de ler os dados: o processo Python precisa descriptografá-los para executar o motor.

Se o processo/servidor em execução for totalmente comprometido, dados em memória podem ser expostos. A defesa adotada reduz superfície e retenção, mas não faz promessa de invulnerabilidade.

## 14. Deploy
- Uvicorn ligado a `0.0.0.0:$PORT`.
- Um worker por padrão, porque o estado e as chaves de sessão são em memória.
- Não escalar horizontalmente ou aumentar workers sem arquitetura compartilhada segura de sessão/chaves ou afinidade de sessão.
- Nenhuma chave privada está no repositório.
- `.env`, certificados e arquivos de chave são ignorados pelo Git.

## 15. Performance sem alteração visual
O HTML do relatório é gerado pelo mesmo motor/template original. A camada web pós-processa somente pontos de custo do JavaScript:
- `Intl.NumberFormat`/`Intl.DateTimeFormat` reutilizados;
- termos de busca em cache;
- texto pesquisável pré-indexado;
- debounce de 180 ms na pesquisa;
- resize por `requestAnimationFrame`;
- GZip para conteúdo textual compatível.

Essas mudanças não modificam cores, temas, gráficos, filtros, cards, cálculos ou a ordem visual.
