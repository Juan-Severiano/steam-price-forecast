// Run with: node --test web/test-contract.mjs
// Evaluate the pure import-validation functions without starting a browser or adding a dependency.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { demoCatalog } from './demo.js';

const source = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
const validation = source.slice(source.indexOf('function validDate('), source.indexOf('function showFeedback('));
const validateCatalog = vm.runInNewContext(`${validation}; validateCatalog`);
const fixture = () => {
  const catalog = structuredClone(demoCatalog);
  catalog.modo = 'local';
  catalog.jogos = [catalog.jogos[0]];
  catalog.jogos[0].data_base = catalog.jogos[0].historico.at(-1).data;
  return catalog;
};

test('accepts matching local dates/prices and demo with inferred base date', () => {
  assert.equal(validateCatalog(fixture()).jogos.length, 1);
  assert.equal(validateCatalog(demoCatalog).jogos[0].data_base, '2026-11-02');
});

test('rejects a prediction from a different base date, including mismatched horizons', () => {
  const catalog = fixture();
  catalog.jogos[0].previsoes['90'].data_base = '2026-11-01';
  assert.throws(() => validateCatalog(catalog), /campos inválidos/);
});

test('rejects a declared game base date different from the final history date', () => {
  const catalog = fixture();
  catalog.jogos[0].data_base = '2026-11-01';
  assert.throws(() => validateCatalog(catalog), /campos inválidos/);
});

test('rejects an invalid explicit base date instead of silently using history', () => {
  const catalog = fixture();
  catalog.jogos[0].data_base = '2026-02-31';
  assert.throws(() => validateCatalog(catalog), /campos inválidos/);
});

test('rejects a current price inconsistent with the final history value', () => {
  const catalog = fixture();
  catalog.jogos[0].preco_atual += 1;
  assert.throws(() => validateCatalog(catalog), /campos inválidos/);
});

test('rejects a regular price inconsistent with the final history value', () => {
  const catalog = fixture();
  catalog.jogos[0].preco_regular += 1;
  assert.throws(() => validateCatalog(catalog), /campos inválidos/);
});

test('accepts a delisted final day with null prices and no predictions', () => {
  const catalog = fixture();
  const game = catalog.jogos[0];
  game.preco_atual = game.preco_regular = null;
  game.historico.at(-1).preco = game.historico.at(-1).regular = null;
  game.previsoes = {};
  assert.equal(validateCatalog(catalog).jogos[0].preco_atual, null);
});

test('rejects stale price when the final day is unavailable', () => {
  const catalog = fixture();
  catalog.jogos[0].historico.at(-1).preco = null;
  assert.throws(() => validateCatalog(catalog), /campos inválidos/);
});
