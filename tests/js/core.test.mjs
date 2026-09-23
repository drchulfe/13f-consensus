import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('../../template.html', import.meta.url), 'utf8');
const src = html.split('/*CORE-BEGIN*/')[1].split('/*CORE-END*/')[0];
const CORE = new Function(`${src}; return CORE;`)();

const K = [0, 21, 63, 126], H = { '1w': 5, '1m': 21, '1y': 252, '3y': 756, '5y': 1260 };
const O = [...new Set([...K.flatMap(k => Object.values(H).map(h => k + h)), ...K])].sort((a, b) => a - b);
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const R = map => { const r = new Array(O.length).fill(null); for (const [o, v] of Object.entries(map)) r[O.indexOf(+o)] = v; return r; };
const F = (o = {}) => ({ anchorSet: null, basis: 'buy', minN: 2, newOnly: false, ...o });

test('offset grid matches python', () => {
  assert.equal(O.length, 23);
  assert.ok(O.includes(63) && O.includes(252) && O.includes(1386));
});

test('median, quantile, winsorized mean', () => {
  assert.equal(CORE.med([3, 1, 2]), 2); assert.equal(CORE.med([1, 2, 3, 4]), 2.5); assert.equal(CORE.med([]), null);
  near(CORE.quant([0, 10], 0.16), 1.6);
  const a = Array.from({ length: 100 }, (_, i) => i); a[99] = 1e6;
  assert.ok(CORE.winsorMean(a) < 200);          // 원평균 ≈ 10,049 → 1% 윈저화 ≈ 149.5
});

test('annualize and band', () => {
  near(CORE.annualize(0.21, 504), 0.1, 1e-12);
  const b = CORE.band(0.1, 0.3, 252);
  near(b[0], Math.exp(Math.log(1.1) - 0.3) - 1); near(b[1], Math.exp(Math.log(1.1) + 0.3) - 1);
  assert.equal(CORE.band(null, 0.3, 5), null);
});

test('decodeBT expands compact events', () => {
  const bt = { K, H, O, P: ['2025-12-31'], I: ['buffett', 'gates'], ev: [[0, 'AAA', [1, 2], 3, [0, 50], 0]], spy: [[0, 20]] };
  const d = CORE.decodeBT(bt);
  assert.deepEqual(d.ev[0].slice(0, 4), ['2025-12-31', 'AAA', [['buffett', 'n'], ['gates', 'a']], 3]);
  assert.equal(d.ev[0][4].length, O.length); near(d.ev[0][4][1], 0.05); assert.equal(d.ev[0][4][5], null);
  near(d.spy[0][1], 0.02);
});

test('evCount respects anchor, newOnly and basis', () => {
  const ev = ['2025-12-31', 'A', [['buffett', 'n'], ['gates', 'a']], 4, R({}), 0];
  assert.equal(CORE.evCount(ev, F()), 2);
  assert.equal(CORE.evCount(ev, F({ basis: 'hold' })), 4);
  assert.equal(CORE.evCount(ev, F({ newOnly: true })), 1);
  assert.equal(CORE.evCount(ev, F({ anchorSet: new Set(['soros']) })), -1);
});

test('stats: horizon returns, cutoff, bucket and SPY excess', () => {
  const b = [['buffett', 'n'], ['gates', 'a']];
  const bt = { K, H, O, spy: [R({ 0: 0, 21: 0.05 })], ev: [
    ['2025-09-30', 'A', b, 2, R({ 0: 0, 21: 0.10 }), 0],
    ['2025-09-30', 'B', b, 2, R({ 0: 0, 21: 0.20 }), 0],
    ['2025-09-30', 'C', b, 2, R({ 0: 0, 21: -0.10 }), 0],
    ['2026-03-31', 'D', b, 2, R({ 0: 0, 21: 0.90 }), 0]] };
  const st = CORE.stats(bt, F(), '2026-03-31', 0, null);
  assert.equal(st.nev, 3); assert.equal(st['1m'].n, 3);
  near(st['1m'].med, 0.10); near(st['1m'].hit, 2 / 3); near(st['1m'].ex, 0.05);
  assert.equal(st['1y'].n, 0);
  assert.equal(CORE.stats(bt, F(), '2026-03-31', 0, 3).nev, 0);
});

test('stats: elapsed k re-bases returns', () => {
  const bt = { K, H, O, spy: [R({})], ev: [['2025-09-30', 'A', [['buffett', 'n'], ['gates', 'n']], 2, R({ 21: 0.10, 42: 0.21 }), 0]] };
  near(CORE.stats(bt, F(), null, 21, null)['1m'].med, 0.1);
});

test('trackRecord chains cohorts with cash for empty quarters', () => {
  const bA = [['buffett', 'n'], ['gates', 'a']], bB = [['soros', 'n'], ['gates', 'a']];
  const bt = { K, H, O, spy: [R({ 63: 0.02, 252: 0.08 }), R({ 63: 0.03 })], ev: [
    ['2025-03-31', 'A', bA, 2, R({ 63: 0.10, 252: 0.30 }), 0],
    ['2025-03-31', 'B', bA, 2, R({ 63: 0.00, 252: 0.10 }), 0],
    ['2025-06-30', 'C', bB, 2, R({ 63: 0.50 }), 1]] };
  const T = CORE.trackRecord(bt, F({ anchorSet: new Set(['buffett']) }));
  assert.equal(T.q, 2);
  near(T.rows[0].r3, 0.05); near(T.rows[0].s3, 0.02); near(T.rows[0].r1, 0.2);
  assert.equal(T.rows[1].n, 0); assert.equal(T.rows[1].r3, 0); near(T.rows[1].s3, 0.03);
  near(T.curve[1].nav, 1.05); near(T.curve[1].snav, 1.02 * 1.03);
  near(T.win, 0.5); near(T.mdd, 0); near(T.cagr, Math.pow(1.05, 2) - 1);
});

test('niceTicks covers range with round steps', () => {
  assert.deepEqual(CORE.niceTicks(0.9, 3.4, 4), [0, 1, 2, 3, 4]);
  const t = CORE.niceTicks(0.95, 1.32, 4);
  assert.ok(t[0] <= 0.95 && t[t.length - 1] >= 1.32);
});

test('recScore: 합의 40 + 가격 40 + 신선도 20, 없는 항목은 평균에서 제외', () => {
  const mk = (n, ancN, px, an) => ({n, ancN, s: {px, an}});
  const full = CORE.recScore(mk(5, 2, {last: 80, prem: -0.20, hi52: 133.33, el: 0, krw: 1}, {mean: 112}), true);
  assert.equal(full.cons, 40);                 // min(30, 6*5)=30 + min(10, 5*2)=10
  assert.equal(full.price, 40);                // 세 항목 모두 만점
  assert.equal(full.fresh, 20);                // 수시 매수 10 + 경과 0일 10
  assert.equal(full.score, 100);
  const none = CORE.recScore(mk(2, 0, null, null), false);
  assert.deepEqual([none.cons, none.price, none.fresh, none.parts], [12, 0, 0, 0]);
  const half = CORE.recScore(mk(2, 0, {last: 100, prem: 0.0, hi52: 100, el: 126, krw: 1}, null), false);
  assert.equal(half.parts, 2);                 // 목표가 없음 → 두 항목 평균
  assert.equal(half.price, 10);                // (0.5 + 0) / 2 * 40
  assert.equal(half.fresh, 0);
});
