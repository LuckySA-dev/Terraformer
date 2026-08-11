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
  clear_enable_password?: boolean;
}

export type DeviceStatus = 'reachable' | 'unreachable' | 'unknown';
export type SshCompatibility = 'modern' | 'cisco_legacy' | 'cisco_legacy_group1' | 'very_old_ssh';
export type Vendor = 'cisco_iosxe' | 'fortinet_fortios' | 'generic';
export type ConsoleTransport = 'ssh' | 'telnet';

/**
 * Which SSH compatibility modes each vendor accepts.
 *
 * Mirrors the guard in backend/app/api/ssh_trust.py. Kept here as the single
 * source for the UI so the form cannot offer a mode the backend will reject
 * only after the operator has filled in the whole form.
 */
export const SSH_MODES_BY_VENDOR: Record<Vendor, readonly SshCompatibility[]> = {
  cisco_iosxe: ['modern', 'cisco_legacy', 'cisco_legacy_group1', 'very_old_ssh'],
  fortinet_fortios: ['modern', 'very_old_ssh'],
  generic: ['modern'],
};

export const SSH_MODE_LABELS: Record<SshCompatibility, { label: string; hint: string }> = {
  modern: {
    label: 'Modern',
    hint: 'Current algorithms only. Correct for anything from roughly the last decade.',
  },
  cisco_legacy: {
    label: 'Cisco legacy',
    hint: 'Adds SHA-1 key exchange and CBC ciphers. Try this first for IOS 15.x.',
  },
  cisco_legacy_group1: {
    label: 'Cisco legacy + Group1',
    hint: 'Also adds diffie-hellman-group1-sha1, for older IOS builds.',
  },
  very_old_ssh: {
    label: 'Very Old SSH',
    hint: 'Adds 3DES, DSA and MD5. Last resort for Catalyst 2960/2960-X and ISR 1941.',
  },
};

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
  vendor: Vendor;
  credential_profile_id: string;
  ssh_compatibility?: SshCompatibility;
  is_lab: boolean;
  console_transport: ConsoleTransport;
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
  vendor: Vendor;
  credential_profile_id: string;
  ssh_compatibility: SshCompatibility;
  is_lab: boolean;
  console_transport: ConsoleTransport;
  group1_risk_acknowledged: boolean;
  very_old_risk_acknowledged: boolean;
  host_key_candidate_id?: string;
}

export interface HostKeyCandidate {
  id: string;
  algorithm: string;
  fingerprint: string;
  expires_at: string;
}

export interface DiscoveryInput {
  cidr: string;
  ports: number[];
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
  ports: number[];
  scanned_count: number;
  concurrency: number;
  candidates: DiscoveryCandidate[];
  open_endpoints: DiscoveryCandidate[];
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
  type:
    | 'refresh_device'
    | 'capture_config'
    | 'discover_ssh'
    | 'run_diagnostic'
    | 'analyze_network';
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

export type AnalysisStatus = 'pending' | 'parsing' | 'ready' | 'failed' | 'expired';
export type ExclusionReason = 'no_snapshot' | 'unsupported_vendor';
export type FindingCategory =
  | 'parse_warning'
  | 'undefined_reference'
  | 'unused_structure'
  | 'topology_drift';

export interface AnalysisExclusion {
  reason: ExclusionReason;
  count: number;
}

export interface AnalysisCompleteness {
  registered_device_count: number;
  analysed_device_count: number;
  observed_link_count: number;
  exclusions: AnalysisExclusion[];
  oldest_config_at: string | null;
  newest_config_at: string | null;
}

export interface AnalysisSnapshot {
  id: string;
  status: AnalysisStatus;
  evidence: 'INFERRED';
  parse_warning_count: number;
  findings_truncated: boolean;
  failure_code: string | null;
  completeness: AnalysisCompleteness;
  created_at: string;
  updated_at: string;
}

export interface AnalysisFinding {
  id: string;
  category: FindingCategory;
  severity: 'info' | 'warning' | 'error';
  device_id: string | null;
  structure_type: string | null;
  structure_name: string | null;
  detail: string;
  line_number: number | null;
  evidence: 'INFERRED';
}

export interface TraceHop {
  hostname: string;
  action: string;
  detail: string;
}

export interface PathCheckResult {
  disposition: string;
  hops: TraceHop[];
  evidence: 'INFERRED';
  completeness: AnalysisCompleteness;
}

export interface FilterCheckResult {
  permitted: boolean;
  matched_line_index: number | null;
  matched_line: string | null;
  evidence: 'INFERRED';
  completeness: AnalysisCompleteness;
}
