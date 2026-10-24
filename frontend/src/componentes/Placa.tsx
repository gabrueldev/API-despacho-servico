/** Placa no padrão Mercosul: faixa azul com "BRASIL" e os caracteres em destaque. */
export function Placa({ placa, tamanho = "normal" }: { placa: string; tamanho?: "normal" | "grande" }) {
  return (
    <span className={`placa placa--${tamanho}`} aria-label={`Placa ${placa.split("").join(" ")}`}>
      <span className="placa__faixa" aria-hidden="true">
        BRASIL
      </span>
      <span className="placa__caracteres" aria-hidden="true">
        {placa}
      </span>
    </span>
  );
}
