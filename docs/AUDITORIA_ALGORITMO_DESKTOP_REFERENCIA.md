# Auditoria determinística — Contas a Pagar 1.1.1

## Fonte de classificação
A classificação usada nos indicadores vem **exclusivamente da BASE DADOS ativa da automação**.

Ordem de classificação:
1. código do fornecedor exatamente igual ao da BASE DADOS;
2. nome normalizado exatamente igual, somente quando existe uma única linha inequívoca na BASE DADOS;
3. similaridade de nome é calculada apenas para sugerir possíveis correspondências no alerta — **nunca altera Categoria, Fluxo JMM, fornecedor canônico ou indicadores**.

Isso evita atribuições silenciosas incorretas. A planilha de referência possui, por exemplo, nomes iguais para códigos/classificações diferentes; por isso similaridade não pode ser fonte automática de classificação.

## Totais financeiros
- **Previsto:** soma integral da coluna `Valor previsto` das linhas PREVISTO validadas.
- **Realizado:** soma integral da coluna `Vlr.Original` das linhas REALIZADO validadas.
- **Desvio:** `Realizado - Previsto`.
- **Variação %:** `(Realizado - Previsto) / Previsto × 100` quando Previsto é diferente de zero.

Não existe deduplicação ou pareamento 1:1 automático entre uma linha prevista e um título realizado. O relatório consolida por chaves de negócio.

## Pontualidade
Compara `Ult. Pgto.` com `Vencimento`:
- pagamento < vencimento → Antecipado;
- pagamento = vencimento → Dentro do Prazo;
- pagamento > vencimento → Atrasado;
- data ausente/inválida → Sem data e fora do denominador da taxa.

Taxa de pontualidade = `(Antecipados + Dentro do Prazo) / títulos com ambas as datas válidas × 100`.

## Contrato da planilha de referência
Para `samples/PLANILHAS PAGAR E PREVISTO.xlsx` com a BASE DADOS incorporada:
- PREVISTO: 96 linhas;
- REALIZADO: 622 linhas;
- BASE DADOS: 180 linhas;
- Previsto: R$ 6.272.858,706;
- Realizado: R$ 8.756.209,59;
- Desvio: R$ 2.483.350,884;
- Variação: 39,5888222642%;
- Pontualidade: 7 antecipados, 606 dentro do prazo, 9 atrasados;
- 88 linhas do REALIZADO, pertencentes a 1 fornecedor/código não existente na BASE DADOS, permanecem `Não classificado`, totalizando R$ 773.533,96.

Essas 88 linhas são auditáveis no relatório com arquivo, aba e linha exata. Na amostra, começam na linha 398 da aba REALIZADO. As sugestões por nome apontam para mais de uma classificação possível na BASE DADOS e, por segurança, não são aplicadas.

## Reconciliação interna dos gráficos
Além dos totais executivos, a validação 1.1.1 verifica que:
- a soma de `planned` de todas as categorias é exatamente o total Previsto;
- a soma de `actual` de todas as categorias é exatamente o total Realizado;
- a soma dos desvios por Fluxo JMM é exatamente `Realizado - Previsto`;
- o último ponto acumulado do gráfico temporal reconcilia com os totais que possuem datas válidas; na planilha de referência todas as 96 linhas PREVISTO e 622 linhas REALIZADO possuem datas temporais válidas;
- a taxa de pontualidade usa somente títulos com pagamento e vencimento válidos.

As mudanças de cor, dimensionamento, hover e animação são exclusivamente de apresentação e **não participam de nenhum cálculo**.


## Auditoria adicional — 1.1.4 / layout consolidado
A planilha de cliente usada para validar esta versão possui uma única aba `Base de dados` com as colunas `Título`, `Tipo`, `Cód Fornecedor`, `Fornecedor`, `Data`, `Previsto`, `Realizado`, `Situação FC`, `Mês`, `Fluxo JMM` e `Categoria`.

A adaptação é deliberadamente estrita:
1. a tabela só é tratada como consolidada se **todos** os campos-chave existirem;
2. `Situação FC = PREVISTO` gera somente registros PREVISTO e usa a coluna `Previsto`;
3. `Situação FC = REALIZADO` gera somente registros REALIZADO e usa `abs(Realizado)`, pois neste layout as 1.364 linhas realizadas usam sinal negativo;
4. a coluna `Data` é usada como data temporal de cada lado;
5. não há `Vencimento`, portanto pontualidade não é inferida;
6. `Fluxo JMM` e `Categoria` da planilha importada não classificam registros. A BASE DADOS fixa continua sendo a única fonte de classificação. Isso é especialmente importante porque a planilha contém fórmulas XLOOKUP com referência externa para essas duas colunas.

### Contrato real do arquivo de cliente analisado
- 290 linhas PREVISTO;
- 1.364 linhas REALIZADO;
- período com dados: maio a julho/2026;
- total PREVISTO extraído deterministicamente: R$ 19.316.472,201513;
- total REALIZADO extraído deterministicamente: R$ 16.066.043,83;
- todas as 1.364 linhas REALIZADO do arquivo usam valor negativo na coluna `Realizado`; a normalização para valor financeiro positivo ocorre somente após a separação por `Situação FC`;
- 2 linhas PREVISTO possuem valor zero e são preservadas como zero;
- não existem outros valores não vazios em `Situação FC` além de PREVISTO/REALIZADO.

A validação com a BASE DADOS padrão encontrou fornecedores ainda não classificados. Eles permanecem `Não classificado`, com alerta auditável; **não existe fallback por similaridade que altere indicador**.


## Adendo web — layout consolidado `Valor` / `Valor2`
Foi validado um segundo contrato explícito para o mesmo layout consolidado. Quando a tabela contém `Título`, `Cód Fornecedor`, `Fornecedor`, `Data`, `Valor`, `Valor2` e `Situação FC`, a automação reconhece esse modelo sem exigir que os cabeçalhos monetários sejam renomeados para `Previsto` e `Realizado`.

Regras determinísticas:
1. `Situação FC = PREVISTO` define a linha como PREVISTO e utiliza exclusivamente `Valor`;
2. `Situação FC = REALIZADO` define a linha como REALIZADO e utiliza exclusivamente `Valor2`;
3. o sinal negativo de `Valor2`, quando presente, só é normalizado com `abs()` depois de a linha estar confirmada como REALIZADO pela `Situação FC`;
4. a existência de números positivos/negativos isoladamente não classifica uma linha;
5. nenhum fallback por posição de coluna ou semelhança de nome é permitido.

No arquivo real `Report prev e real.xlsx` usado para validação desta alteração:
- 290 linhas foram identificadas como PREVISTO;
- 1.364 linhas foram identificadas como REALIZADO;
- o total PREVISTO lido de `Valor` foi R$ 19.316.472,201513;
- o total REALIZADO lido de `abs(Valor2)` foi R$ 16.066.043,83;
- 1.364/1.364 linhas REALIZADO possuíam `Valor2` negativo;
- 2 linhas PREVISTO possuíam valor zero e foram preservadas.

Esse adendo altera somente a detecção do contrato de entrada. Reconciliação, classificação, métricas, PDF, Excel, relatório, filtros, gráficos, cores e temas permanecem inalterados.
