export interface BotStatus {
  name?: string
  health: number
  food: number
  saturation?: number
  position: { x: number; y: number; z: number }
  dimension: string
  xp_level?: number
  xp_points?: number
  alive: boolean
  is_alive?: boolean
  gamemode?: string
}

export interface InventorySlot {
  slot: number
  item: string
  count: number
  display_name?: string
}

export interface BotSnapshot {
  name: string
  model: string
  specializations: string[]
  status: BotStatus
  inventory: InventorySlot[]
  entities: Entity[]
  plan: {
    instruction: string
    steps: string[]
    step_idx: number
  }
  awaiting_taskboard: boolean
  current_task_id: number | null
  l3_retries: number
  l4_escalations: number
}

export interface Entity {
  name: string
  type: string
  distance: number
  health?: number
}

export interface ServerState {
  version: number
  bots: Record<string, BotSnapshot>
  server: Record<string, unknown>
}

export interface DashEvent {
  ts: number
  bot?: string
  type: string
  [key: string]: unknown
}

export interface Waypoint {
  name: string
  x: number
  y: number
  z: number
  dimension: string | null
  set_by: string | null
}

export interface DirectiveParam {
  name: string
  type: string
  label: string
  required: boolean
  default?: unknown
  options?: string[]
}

export interface DirectiveDef {
  type: string
  label: string
  params: DirectiveParam[]
}
