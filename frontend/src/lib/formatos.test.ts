import { describe, expect, it } from "vitest";

import { distanciaAte } from "./formatos";

describe("distanciaAte", () => {
  it("mostra metros quando o guincho está perto, sem cair para 0", () => {
    expect(distanciaAte(12)).toBe("50 m");
    expect(distanciaAte(430)).toBe("450 m");
  });

  it("passa para km a partir de 1 km", () => {
    expect(distanciaAte(2300)).toMatch(/^2,3 km$/);
  });
});
