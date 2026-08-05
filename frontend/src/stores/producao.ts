/**
 * Estado de produção por OS (zustand): segmento/certificado (T5), criativo (T6),
 * jornada+taxímetro (T7), ensaio/cenários (T8), snapshot+link mágico (T9/T10) e
 * launch (T11/T12). O SDD §8 não expõe GET para esses recursos — o estado nasce das
 * mutações (POST gerar / recontar / simular / snapshots / armar…) e sobrevive à
 * navegação entre telas (ex.: T7 → T8 → T9 → T11 → T12).
 */
import { create } from "zustand";

import type {
  CertificadoOut,
  CriativoOut,
  JornadaOut,
  JornadaSimuladaOut,
  LaunchOut,
  LinkMagicoOut,
  SegmentoOut,
  SnapshotOut,
  TaximetroOut,
} from "../lib/types";

export interface JornadaComTaximetro {
  jornada: JornadaOut;
  taximetro: TaximetroOut;
  /** resumo narrado pelo flow no gerar (via_ai) */
  resumo?: string;
}

/** Cenário simulado (T8): versão do twin com simulação persistida — comparável. */
export interface CenarioRegistrado {
  jornada_id: string;
  versao: number;
  hash: string;
  rotulo: string;
}

interface ProducaoState {
  /** por osId */
  segmentos: Record<string, SegmentoOut>;
  certificados: Record<string, CertificadoOut>;
  criativos: Record<string, CriativoOut>;
  jornadas: Record<string, JornadaComTaximetro>;
  ensaios: Record<string, JornadaSimuladaOut>;
  cenarios: Record<string, CenarioRegistrado[]>;
  snapshots: Record<string, SnapshotOut>;
  linksMagicos: Record<string, LinkMagicoOut>;
  launches: Record<string, LaunchOut>;

  setSegmento: (osId: string, s: SegmentoOut) => void;
  setCertificado: (osId: string, c: CertificadoOut) => void;
  limparCertificado: (osId: string) => void;
  setCriativo: (osId: string, c: CriativoOut) => void;
  setJornada: (osId: string, j: JornadaComTaximetro) => void;
  setEnsaio: (osId: string, e: JornadaSimuladaOut) => void;
  registrarCenario: (osId: string, c: CenarioRegistrado) => void;
  setSnapshot: (osId: string, s: SnapshotOut) => void;
  setLinkMagico: (osId: string, l: LinkMagicoOut) => void;
  setLaunch: (osId: string, l: LaunchOut) => void;
}

export const useProducao = create<ProducaoState>((set) => ({
  segmentos: {},
  certificados: {},
  criativos: {},
  jornadas: {},
  ensaios: {},
  cenarios: {},
  snapshots: {},
  linksMagicos: {},
  launches: {},

  setSegmento: (osId, s) => set((e) => ({ segmentos: { ...e.segmentos, [osId]: s } })),
  setCertificado: (osId, c) =>
    set((e) => ({ certificados: { ...e.certificados, [osId]: c } })),
  limparCertificado: (osId) =>
    set((e) => {
      const { [osId]: _descartado, ...resto } = e.certificados;
      return { certificados: resto };
    }),
  setCriativo: (osId, c) => set((e) => ({ criativos: { ...e.criativos, [osId]: c } })),
  setJornada: (osId, j) => set((e) => ({ jornadas: { ...e.jornadas, [osId]: j } })),
  setEnsaio: (osId, en) => set((e) => ({ ensaios: { ...e.ensaios, [osId]: en } })),
  registrarCenario: (osId, c) =>
    set((e) => {
      const atuais = e.cenarios[osId] ?? [];
      const semEle = atuais.filter((x) => x.jornada_id !== c.jornada_id);
      return { cenarios: { ...e.cenarios, [osId]: [...semEle, c] } };
    }),
  setSnapshot: (osId, s) => set((e) => ({ snapshots: { ...e.snapshots, [osId]: s } })),
  setLinkMagico: (osId, l) =>
    set((e) => ({ linksMagicos: { ...e.linksMagicos, [osId]: l } })),
  setLaunch: (osId, l) => set((e) => ({ launches: { ...e.launches, [osId]: l } })),
}));
