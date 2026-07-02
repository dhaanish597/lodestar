// frontend/lib/types.ts
export interface Vessel {
  mmsi: number;
  lat: number;
  lon: number;
  sog: number;
  cog: number | null;
  true_heading: number | null;
  nav_status: number | null;
  timestamp: string;
  valid: boolean;
  signal_lost: boolean;
  extrapolated: boolean;
}

export interface RiskScore {
  corridor: string;
  timestamp: string;
  probability: number;
  beta0: number;
  weights: Record<string, number>;
  features: Record<string, number>;
  contributions: Record<string, number>;
}

export interface Scenario {
  corridor: string;
  disruption_factor: number;
  substitution_rate: number;
  hormuz_share: number;
  india_imports_mbd: number;
  supply_gap_mbd: number;
  utilization_drop_pct: number;
  spr_fill_pct: number;
  days_cover_remaining: number;
  cpi_sensitivity: number;
  cpi_delta_pp: number;
  gdp_drag_bps: number;
  cad_sensitivity: number;
  cad_widening_pct_gdp: number;
}

export interface RerouteOption {
  source_grade: string;
  origin: string;
  api_gravity: number;
  sulfur_pct: number;
  landed_cost_usd_bbl: number;
  voyage_days: number;
  grade_match: number;
  congestion_penalty: number;
  score: number;
  best_fit_refineries: string[];
}
