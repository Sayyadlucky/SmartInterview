export function getApiBaseUrl(): string {
  let port = '';
  if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
    port = '8080';
  }
  return `${window.location.protocol}//${window.location.hostname}${port ? `:${port}` : ''}`;
}
