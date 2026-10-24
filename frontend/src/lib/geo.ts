import type { Ponto } from "../api/tipos";

const RAIO_TERRA_M = 6_371_000;
const rad = (graus: number) => (graus * Math.PI) / 180;

/** Distância em metros (haversine): suficiente para o simulador e para exibir. */
export function distanciaM(a: Ponto, b: Ponto): number {
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * RAIO_TERRA_M * Math.asin(Math.sqrt(h));
}

/**
 * Próxima posição do simulador: anda até `passoM` metros em direção ao alvo, em linha reta.
 * Se o alvo está mais perto que um passo, chega nele (sem passar do ponto).
 */
export function avancarAte(atual: Ponto, alvo: Ponto, passoM: number): Ponto {
  const restante = distanciaM(atual, alvo);
  if (restante <= passoM) return { ...alvo };
  const fracao = passoM / restante;
  return {
    lat: atual.lat + (alvo.lat - atual.lat) * fracao,
    lng: atual.lng + (alvo.lng - atual.lng) * fracao,
  };
}
