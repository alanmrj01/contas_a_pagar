import { FileBlob, SpreadsheetFile } from "file:///C:/Users/Alan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const paths = [
  ".audit_output/previsto/Previsto_filtrado.xlsx",
  ".audit_output/realizado/Realizado_filtrado.xlsx",
  ".audit_output/atualizado/Relatorio_atualizado_filtrado.xlsx",
];

for (const path of paths) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  const summary = await workbook.inspect({
    kind: "workbook,sheet,table",
    maxChars: 5000,
    tableMaxRows: 4,
    tableMaxCols: 20,
    tableMaxCellChars: 80,
  });
  const formulas = await workbook.inspect({kind: "formula", maxChars: 1000});
  console.log(`\n### ${path}\n${summary.ndjson}\nFORMULAS\n${formulas.ndjson || "(none)"}`);
}
