// Entirely synthetic examples. These values are not quotes or ITAD observations.
const BASE_DATE = '2026-11-02';
const DAY = 86_400_000;
const base = Date.parse(`${BASE_DATE}T00:00:00Z`);
const games = [
  { appid: 413150, titulo: 'Stardew Valley', categoria: 'Vida no campo · Cooperativo', preco: 36, regular: 36, chance: [0.68, 0.87], quantis: [[18, 24, 36], [14.4, 18, 28.8]], color: '#427d83', pattern: [1, 1, .7, 1, 1, .6, 1, 1, 1, .5, 1, 1] },
  { appid: 1145360, titulo: 'Hades', categoria: 'Roguelike · Ação', preco: 70, regular: 100, chance: [0.42, 0.75], quantis: [[45, 70, 70], [35, 50, 70]], color: '#ab4d42', pattern: [1, .8, 1, 1, .6, 1, 1, .7, 1, 1, 1, .7] },
  { appid: 1091500, titulo: 'Cyberpunk 2077', categoria: 'RPG · Mundo aberto', preco: 180, regular: 180, chance: [0.73, 0.91], quantis: [[72, 108, 180], [54, 72, 126]], color: '#a8982b', pattern: [1, 1, .6, 1, .6, 1, 1, .5, 1, 1, .4, 1] },
  { appid: 1245620, titulo: 'Elden Ring', categoria: 'RPG · Fantasia sombria', preco: 240, regular: 240, chance: [0.31, 0.61], quantis: [[168, 240, 240], [144, 192, 240]], color: '#918356', pattern: [1, 1, 1, .8, 1, 1, 1, 1, .7, 1, 1, 1] },
  { appid: 367520, titulo: 'Hollow Knight', categoria: 'Metroidvania · Aventura', preco: 42, regular: 42, chance: [0.57, 0.82], quantis: [[21, 31.5, 42], [16.8, 21, 37.8]], color: '#5d6e98', pattern: [1, 1, .75, 1, 1, 1, .5, 1, 1, .75, 1, 1] },
  { appid: 105600, titulo: 'Terraria', categoria: 'Sandbox · Sobrevivência', preco: 28, regular: 28, chance: [0.64, 0.85], quantis: [[14, 21, 28], [11.2, 14, 22.4]], color: '#5c9663', pattern: [1, .75, 1, 1, .5, 1, 1, .75, 1, 1, .5, 1] },
  { appid: 620, titulo: 'Portal 2', categoria: 'Quebra-cabeça · Cooperativo', preco: 32, regular: 32, chance: [0.78, 0.94], quantis: [[3.2, 8, 32], [3.2, 4.8, 16]], color: '#487eaa', pattern: [1, 1, .25, 1, 1, .1, 1, 1, .2, 1, .25, 1] },
  { appid: 1086940, titulo: "Baldur's Gate 3", categoria: 'RPG · Estratégia', preco: 210, regular: 210, chance: [0.38, 0.72], quantis: [[147, 210, 210], [126, 157.5, 210]], color: '#825d55', pattern: [1, 1, .9, 1, 1, .85, 1, 1, 1, .8, 1, 1] },
];
export const demoCatalog = {
  schema_version: 1,
  modo: 'demo',
  gerado_em: '2026-11-03T00:00:00Z',
  fonte: 'Dados sintéticos para demonstração; não são cotações.',
  moeda: 'BRL',
  jogos: games.map((g) => ({
    appid: g.appid, titulo: g.titulo, categoria: g.categoria, cor: g.color,
    preco_atual: g.preco, preco_regular: g.regular,
    desconto_atual: Math.round((1 - g.preco / g.regular) * 100),
    historico: Array.from({ length: 181 }, (_, i) => ({
      data: new Date(base - (180 - i) * DAY).toISOString().slice(0, 10),
      preco: i === 180 ? g.preco : Math.round(g.regular * g.pattern[Math.min(11, Math.floor(i / 15))] * 100) / 100,
      regular: g.regular,
    })),
    previsoes: Object.fromEntries([30, 90].map((h, i) => [h, {
      probabilidade_desconto: g.chance[i], preco_minimo_p10: g.quantis[i][0],
      preco_minimo_p50: g.quantis[i][1], preco_minimo_p90: g.quantis[i][2], data_base: BASE_DATE,
    }])),
  })),
};
