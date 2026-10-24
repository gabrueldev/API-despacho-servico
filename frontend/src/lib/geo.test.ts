import { describe, expect, it } from "vitest";

import { loginDemo } from "./formatos";
import { avancarAte, distanciaM } from "./geo";

const SE = { lat: -23.5503, lng: -46.6339 };
const GRU = { lat: -23.4356, lng: -46.4731 };

describe("distanciaM", () => {
  it("bate com a geodésica do PostGIS (Sé → Guarulhos ≈ 21 km)", () => {
    expect(distanciaM(SE, GRU) / 1000).toBeCloseTo(20.96, 0);
  });

  it("é zero para o mesmo ponto", () => {
    expect(distanciaM(SE, SE)).toBe(0);
  });
});

describe("avancarAte", () => {
  it("anda exatamente um passo em direção ao alvo", () => {
    const depois = avancarAte(SE, GRU, 700);

    expect(distanciaM(SE, depois)).toBeCloseTo(700, -1);
    expect(distanciaM(depois, GRU)).toBeCloseTo(distanciaM(SE, GRU) - 700, -1);
  });

  it("chega no alvo sem passar dele", () => {
    const perto = avancarAte(GRU, SE, distanciaM(GRU, SE) - 100);

    expect(avancarAte(perto, SE, 700)).toEqual(SE);
  });
});

describe("loginDemo", () => {
  it("deriva o e-mail do seed a partir do nome", () => {
    expect(loginDemo("Guincho 007")).toBe("prestador7@despacha.dev");
    expect(loginDemo("Guincho Rápido")).toBeNull();
  });
});
