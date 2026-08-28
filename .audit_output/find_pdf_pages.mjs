import fs from "node:fs/promises";
import * as pdfjs from "file:///C:/Users/Alan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/pdfjs-dist/legacy/build/pdf.mjs";

const data = new Uint8Array(await fs.readFile(".audit_output/report/Relatorio_Contas_a_Pagar.pdf"));
const pdf = await pdfjs.getDocument({data, disableFontFace: true}).promise;
for (let index = 1; index <= pdf.numPages; index += 1) {
  const page = await pdf.getPage(index);
  const content = await page.getTextContent();
  const text = content.items.map((item) => item.str).join(" ");
  if (text.includes("Previsto x Realizado por categoria") || text.includes("Previsto x Realizado por mês")) {
    console.log(index, text.slice(0, 220));
  }
}
