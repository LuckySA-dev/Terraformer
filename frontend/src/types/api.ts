export type ServiceState = 'ok' | 'degraded' | 'unavailable';

export interface HealthCheck {
  status: ServiceState;
}

export interface HealthResponse {
  status: ServiceState;
  version: string;
  checks: {
    database: HealthCheck;
    redis: HealthCheck;
    worker: HealthCheck;
  };
}

export interface SetupStatus {
  configured: boolean;
}

export interface SessionStatus {
  authenticated: boolean;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string;
  };
}

export interface CredentialProfile {
  id: string;
  name: string;
  has_username: boolean;
  has_password: boolean;
  has_enable_password: boolean;
  created_at: string;
  updated_at: string;
}

export interface CredentialProfileInput {
  name: string;
  username: string;
  password: string;
  enable_password?: string;
}

export type DeviceStatus = 'reachable' | 'unreachable' | 'unknown';

export interface DeviceFacts {
  hostname?: string | null;
  vendor?: string | null;
  model?: string | null;
  serial_number?: string | null;
  os_version?: string | null;
  uptime_seconds?: number | null;
  uptime?: string | null;
}

export interface DeviceCapability {
  name: string;
  supported: boolean;
  safety_level: 'D';
}

export interface Device {
  id: string;
  name: string;
  management_address: string;
  port: number;
  vendor: 'cisco_iosxe' | 'generic';
  credential_profile_id: string;
  status: DeviceStatus;
  facts: DeviceFacts;
  capabilities: DeviceCapability[];
  last_seen_at: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeviceInput {
  name: string;
  management_address: string;
  port: number;
  vendor: 'cisco_iosxe' | 'generic';
  credential_profile_id: string;
}

export interface DiscoveryInput {
  cidr: string;
  port: number;
  concurrency: number;
  connect_timeout_seconds: number;
  probe_delay_ms: number;
}

export interface DiscoveryCandidate {
  management_address: string;
  port: number;
}

export interface DiscoveryResult {
  cidr: string;
  port: number;
  scanned_count: number;
  concurrency: number;
  candidates: DiscoveryCandidate[];
}

export type DiagnosticAction =
  | 'routing_table'
  | 'arp_table'
  | 'mac_table'
  | 'ping'
  | 'traceroute';

export interface DiagnosticResult {
  device_id: string;
  action: DiagnosticAction;
  target?: string | null;
  output: string;
  truncated: boolean;
}

export interface ConnectionTestResult {
  reachable: boolean;
  driver: string;
  message: string;
  latency_ms: number;
}

export interface DeviceInterface {
  id: string;
  device_id: string;
  name: string;
  description: string | null;
  admin_up: boolean | null;
  oper_up: boolean | null;
  mac_address: string | null;
  speed_mbps: number | null;
  ipv4_addresses: string[];
  created_at: string;
  updated_at: string;
}

export interface DeviceNeighbor {
  id: string;
  device_id: string;
  protocol: 'cdp' | 'lldp';
  local_interface: string;
  remote_device_name: string;
  remote_interface: string;
  management_address: string | null;
  platform: string | null;
  created_at: string;
  updated_at: string;
}

export interface FactsResponse {
  device_id: string;
  facts: DeviceFacts;
  last_seen_at: string | null;
}

export interface ConfigSnapshot {
  id: string;
  device_id: string;
  sha256: string;
  plaintext_size: number;
  compressed_size: number;
  ciphertext_size: number;
  compression: string;
  encryption: string;
  source: string;
  content?: string;
  created_at: string;
}

export type JobState = 'queued' | 'started' | 'succeeded' | 'failed' | 'cancelled';

export interface Job {
  id: string;
  type: 'refresh_device' | 'capture_config' | 'discover_ssh' | 'run_diagnostic';
  state: JobState;
  device_id: string | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EventRecord {
  id: string;
  device_id?: string | null;
  job_id: string | null;
  event_type: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
  details: Record<string, unknown>;
  created_at: string;
}
