interface WorkspaceContext {
  loginUserName: string;
  loginUserRole: string;
  companyProfile: Record<string, any> | null;
}

const STORAGE_KEY = 'smartInterview.workspaceContext';

export function readWorkspaceContext(): WorkspaceContext | null {
  if (typeof window === 'undefined') {
    return null;
  }

  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as WorkspaceContext;
    return {
      loginUserName: parsed?.loginUserName || '',
      loginUserRole: parsed?.loginUserRole || '',
      companyProfile: parsed?.companyProfile || null,
    };
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function writeWorkspaceContext(context: WorkspaceContext): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
    loginUserName: context.loginUserName || '',
    loginUserRole: context.loginUserRole || '',
    companyProfile: context.companyProfile || null,
  }));
}
