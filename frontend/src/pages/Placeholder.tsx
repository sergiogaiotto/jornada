/**
 * Placeholder padrão das telas ainda não implementadas — mantém o roteamento §12
 * completo e o contrato do shell (painel contextual com copiloto).
 */
import { Copiloto } from "../components/ai/Copiloto";
import { EstadoVazio, TituloTela } from "../components/ui/basics";
import { usePainelContextual } from "../lib/hooks";

interface Props {
  tela: string; //  ex.: "T7"
  titulo: string;
  descricao: string;
  /** módulo/endpoints do SDD §8 que esta tela consumirá */
  contrato: string;
}

export function Placeholder({ tela, titulo, descricao, contrato }: Props) {
  usePainelContextual(
    <>
      <div className="ctx-title">Copiloto</div>
      <Copiloto titulo={`${tela} · em construção`}>
        Esta tela seguirá o contrato de UX da IA: prévia/diff com Aplicar/Rejeitar, chips
        de premissas e badge via_ai clicável.
      </Copiloto>
    </>,
    [tela],
  );

  return (
    <div>
      <TituloTela titulo={`${tela} · ${titulo}`} subtitulo={descricao} />
      <EstadoVazio>
        Em construção — contrato de API (SDD §8): <code>{contrato}</code>
      </EstadoVazio>
    </div>
  );
}
