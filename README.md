# Contas a Pagar Web 2.0.2.0

Migração web da versão desktop 2.0.2, preservando o núcleo determinístico e o relatório final.

## Fluxo
1. Adicionar um ou mais arquivos financeiros (.xlsx, .xls, .xlsm, .xlsb).
2. Validar arquivo com o mesmo motor de detecção, normalização, classificação e reconciliação.
3. Gerar relatório. A aba atual navega para o mesmo relatório HTML usado pela versão desktop, com os mesmos temas, filtros, gráficos, cards, cálculos e exportações.

A Base de Dados continua separada e pode ser consultada, exportada e substituída. Bases personalizadas ficam isoladas por sessão do navegador.

## Executar no Windows
Execute `run_web.bat`. O script cria `.venv`, instala `requirements.txt`, inicia o FastAPI e abre `http://127.0.0.1:8000`.

## Hospedagem
O projeto é um único serviço FastAPI. Pode ser implantado em Render, Railway, Azure, AWS, servidor interno ou Docker.

Render:
- Build: `pip install -r requirements.txt`
- Start: `sh start.sh`
- Health check: `/healthz`

`render.yaml` e `Dockerfile` estão incluídos.

## Persistência
Por padrão, dados do servidor ficam em `runtime_data/`. Para um volume persistente, defina `WEB_DATA_DIR`.

Os arquivos financeiros brutos enviados são apagados do diretório de upload após a validação. Os dados validados necessários à geração ficam em memória e as saídas HTML/PDF/Excel permanecem no diretório de relatórios.

## Segurança
Na versão desktop, a planilha era processada no próprio computador. Em uma hospedagem web externa, o navegador precisa enviar a planilha ao servidor. Para dados corporativos, hospede a aplicação somente em infraestrutura aprovada pela organização.

Cada navegador recebe um identificador aleatório em cookie HttpOnly. Uploads, base personalizada e relatórios são separados por sessão. Somente os relatórios gerados são servidos como arquivos públicos por URL de sessão aleatória.

## Paridade com a versão desktop
`docs/CORE_PARITY_SHA256.json` registra os SHA-256 dos módulos críticos copiados byte a byte da versão desktop 2.0.2, incluindo reconciliador, métricas, detector de layouts, normalização, PDF, Excel, base padrão e `app/report/report_template.html`.

## Testes
Instale `requirements-dev.txt` e execute `pytest -q`.

A entrega foi validada com:
- compileall Python;
- `node --check` no JavaScript;
- 43/43 testes aprovados;
- teste ponta a ponta com a planilha de amostra: validação, geração do HTML, PDF e downloads;
- verificação SHA-256 dos arquivos críticos.

## Arquivos principais
- `main.py`: API/servidor web.
- `webapp/engine.py`: adaptador web para o motor original.
- `webapp/templates/index.html`: tela inicial em três etapas.
- `webapp/static/`: interface web.
- `app/services/`: lógica determinística preservada.
- `app/report/report_template.html`: relatório final preservado.
- `resources/base_dados_padrao.xlsx`: base padrão preservada.

DataTech - AMRJ
