import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';
import { readFile } from 'node:fs/promises';
const generated =
  COMMENT_HEADER +
  astToString(await openapiTS(new URL('../../docs/api/openapi.json', import.meta.url)));
const checkedIn = await readFile(new URL('../src/types/generated.ts', import.meta.url), 'utf8');
if (generated.replace(/\r\n/g, '\n') !== checkedIn.replace(/\r\n/g, '\n')) {
  throw new Error('OpenAPI types changed. Run npm run types:generate and review the diff.');
}
console.log('OpenAPI types are current.');
