import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect } from "react";
import { MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";

import type { Ponto } from "../api/tipos";

export type TipoMarcador = "origem" | "destino" | "livre" | "ao-vivo";

export interface Marcador {
  id: string;
  ponto: Ponto;
  tipo: TipoMarcador;
  rotulo: string;
  destaque?: boolean;
  aoClicar?: () => void;
}

const LETRA: Record<TipoMarcador, string> = { origem: "A", destino: "B", livre: "", "ao-vivo": "" };
const icones = new Map<string, L.DivIcon>();

// divIcon (HTML + CSS) em vez das imagens padrão do Leaflet: nada de asset quebrado no bundle,
// e o visual segue os tokens de cor da página.
function icone(tipo: TipoMarcador, destaque: boolean): L.DivIcon {
  const chave = `${tipo}:${destaque}`;
  let existente = icones.get(chave);
  if (!existente) {
    existente = L.divIcon({
      className: `marcador marcador--${tipo}${destaque ? " marcador--destaque" : ""}`,
      html: `<span>${LETRA[tipo]}</span>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
    icones.set(chave, existente);
  }
  return existente;
}

/** Reenquadra quando `chave` muda (outro chamado), não a cada atualização das posições. */
function Enquadrar({ pontos, chave, painelADireita }: { pontos: Ponto[]; chave: string; painelADireita: boolean }) {
  const mapa = useMap();
  useEffect(() => {
    if (pontos.length === 0) return;
    const limites = L.latLngBounds(pontos.map((p) => [p.lat, p.lng] as [number, number]));
    // Em tela larga o painel do chamado cobre a direita do mapa: os pontos ficam à esquerda dele.
    const coberto = painelADireita && window.matchMedia("(min-width: 901px)").matches ? 400 : 0;
    mapa.fitBounds(limites, { paddingTopLeft: [48, 48], paddingBottomRight: [48 + coberto, 48], maxZoom: 15 });
    // `pontos` fica de fora de propósito: as posições mudam a cada atualização.
  }, [chave, mapa]);
  return null;
}

const SAO_PAULO: Ponto = { lat: -23.5503, lng: -46.6339 };

export function Mapa({
  marcadores,
  trajeto,
  chave,
  rotulo,
  painelADireita = false,
}: {
  marcadores: Marcador[];
  trajeto?: [Ponto, Ponto];
  chave: string;
  rotulo: string;
  painelADireita?: boolean;
}) {
  return (
    <div className="mapa" role="region" aria-label={rotulo}>
      <MapContainer center={[SAO_PAULO.lat, SAO_PAULO.lng]} zoom={11} scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {trajeto && (
          <Polyline
            positions={trajeto.map((p) => [p.lat, p.lng] as [number, number])}
            pathOptions={{ className: "trajeto" }}
          />
        )}
        {marcadores.map((m) => (
          <Marker
            key={m.id}
            position={[m.ponto.lat, m.ponto.lng]}
            icon={icone(m.tipo, Boolean(m.destaque))}
            eventHandlers={m.aoClicar ? { click: m.aoClicar } : undefined}
            keyboard={Boolean(m.aoClicar)}
            title={m.rotulo}
          >
            <Tooltip direction="top" offset={[0, -14]}>
              {m.rotulo}
            </Tooltip>
          </Marker>
        ))}
        <Enquadrar pontos={marcadores.map((m) => m.ponto)} chave={chave} painelADireita={painelADireita} />
      </MapContainer>
    </div>
  );
}
