import { apiRequest, apiRequestWithStatus } from './client';
import type {
  AnalysisFinding,
  AnalysisSnapshot,
  ConfigSnapshot,
  ConnectionTestResult,
  CredentialProfile,
  CredentialProfileInput,
  Device,
  DiagnosticAction,
  FactsResponse,
  DeviceInput,
  DiscoveryInput,
  DeviceInterface,
  DeviceNeighbor,
  EventRecord,
  FilterCheckResult,
  FindingCategory,
  HealthResponse,
  Job,
  HostKeyCandidate,
  PathCheckResult,
  SessionStatus,
  SetupStatus,
} from '../types/api';

const json = (value: unknown): string => JSON.stringify(value);

export const api = {
  health: () => apiRequestWithStatus<HealthResponse>('/health', [503]),
  setupStatus: () => apiRequest<SetupStatus>('/setup'),
  setup: (masterPassword: string) =>
    apiRequest<SetupStatus>('/setup', {
      method: 'POST',
      body: json({ master_password: masterPassword }),
    }),
  session: () => apiRequest<SessionStatus>('/session'),
  login: (masterPassword: string) =>
    apiRequest<SessionStatus>('/session', {
      method: 'POST',
      body: json({ master_password: masterPassword }),
    }),
  logout: async (): Promise<void> => {
    await apiRequest<unknown>('/session', { method: 'DELETE' });
  },

  credentialProfiles: () => apiRequest<CredentialProfile[]>('/credential-profiles'),
  createCredentialProfile: (input: CredentialProfileInput) =>
    apiRequest<CredentialProfile>('/credential-profiles', { method: 'POST', body: json(input) }),
  updateCredentialProfile: (id: string, input: Partial<CredentialProfileInput>) =>
    apiRequest<CredentialProfile>(`/credential-profiles/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: json(input),
    }),
  deleteCredentialProfile: async (id: string): Promise<void> => {
    await apiRequest<unknown>(`/credential-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },

  devices: () => apiRequest<Device[]>('/devices'),
  device: (id: string) => apiRequest<Device>(`/devices/${encodeURIComponent(id)}`),
  createDevice: (input: DeviceInput) =>
    apiRequest<Device>('/devices', { method: 'POST', body: json(input) }),
  updateDevice: (id: string, input: DeviceInput) =>
    apiRequest<Device>(`/devices/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: json(input),
    }),
  deleteDevice: async (id: string): Promise<void> => {
    await apiRequest<unknown>(`/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
  },
  testCandidateConnection: ({
    management_address,
    port,
    vendor,
    credential_profile_id,
    ssh_compatibility,
    group1_risk_acknowledged,
    very_old_risk_acknowledged,
    host_key_candidate_id,
  }: DeviceInput) =>
    apiRequest<ConnectionTestResult>('/devices/connection-test', {
      method: 'POST',
      body: json({
        management_address,
        port,
        vendor,
        credential_profile_id,
        ssh_compatibility,
        group1_risk_acknowledged,
        very_old_risk_acknowledged,
        host_key_candidate_id,
      }),
    }),
  collectHostKeyCandidate: ({
    management_address,
    port,
    vendor,
    credential_profile_id,
    ssh_compatibility,
    group1_risk_acknowledged,
    very_old_risk_acknowledged,
  }: DeviceInput) =>
    apiRequest<HostKeyCandidate>('/ssh-host-key-candidates', {
      method: 'POST',
      body: json({
        management_address,
        port,
        vendor,
        credential_profile_id,
        ssh_compatibility,
        group1_risk_acknowledged,
        very_old_risk_acknowledged,
      }),
    }),
  testDeviceConnection: (id: string) =>
    apiRequest<ConnectionTestResult>(`/devices/${encodeURIComponent(id)}/test-connection`, {
      method: 'POST',
    }),
  refreshDevice: (id: string) =>
    apiRequest<Job>(`/devices/${encodeURIComponent(id)}/refresh`, { method: 'POST' }),
  runDiagnostic: (deviceId: string, action: DiagnosticAction, target?: string) =>
    apiRequest<Job>('/diagnostics', {
      method: 'POST',
      body: json({ device_id: deviceId, action, target }),
    }),
  startDiscovery: (input: DiscoveryInput) =>
    apiRequest<Job>('/discovery-jobs', { method: 'POST', body: json(input) }),
  approveDiscoveryCandidate: (jobId: string, input: DeviceInput) =>
    apiRequest<Device>(`/discovery-jobs/${encodeURIComponent(jobId)}/approve`, {
      method: 'POST',
      body: json(input),
    }),
  facts: (id: string) => apiRequest<FactsResponse>(`/devices/${encodeURIComponent(id)}/facts`),
  interfaces: (id: string) =>
    apiRequest<DeviceInterface[]>(`/devices/${encodeURIComponent(id)}/interfaces`),
  neighbors: (id: string) =>
    apiRequest<DeviceNeighbor[]>(`/devices/${encodeURIComponent(id)}/neighbors`),
  captureSnapshot: (id: string) =>
    apiRequest<Job>(`/devices/${encodeURIComponent(id)}/config-snapshots`, { method: 'POST' }),
  snapshots: (deviceId: string) =>
    apiRequest<ConfigSnapshot[]>(`/config-snapshots?device_id=${encodeURIComponent(deviceId)}`),
  snapshot: (id: string) => apiRequest<ConfigSnapshot>(`/config-snapshots/${encodeURIComponent(id)}`),
  events: (deviceId?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (deviceId !== undefined) params.set('device_id', deviceId);
    return apiRequest<EventRecord[]>(`/events?${params.toString()}`);
  },
  job: (id: string) => apiRequest<Job>(`/jobs/${encodeURIComponent(id)}`),

  analysisSnapshots: () => apiRequest<AnalysisSnapshot[]>('/analysis-snapshots'),
  startAnalysis: () => apiRequest<Job>('/analysis-snapshots', { method: 'POST' }),
  analysisFindings: (id: string, category?: FindingCategory) => {
    const params = new URLSearchParams();
    if (category !== undefined) params.set('category', category);
    const query = params.toString();
    return apiRequest<AnalysisFinding[]>(
      `/analysis-snapshots/${encodeURIComponent(id)}/findings${query === '' ? '' : `?${query}`}`,
    );
  },
  pathCheck: (id: string, sourceDeviceId: string, destinationIp: string) =>
    apiRequest<PathCheckResult>(`/analysis-snapshots/${encodeURIComponent(id)}/path-checks`, {
      method: 'POST',
      body: json({ source_device_id: sourceDeviceId, destination_ip: destinationIp }),
    }),
  filterCheck: (
    id: string,
    input: {
      device_id: string;
      filter_name: string;
      destination_ip: string;
      protocol: 'tcp' | 'udp' | 'icmp';
      destination_port?: number;
    },
  ) =>
    apiRequest<FilterCheckResult>(`/analysis-snapshots/${encodeURIComponent(id)}/filter-checks`, {
      method: 'POST',
      body: json(input),
    }),
};
