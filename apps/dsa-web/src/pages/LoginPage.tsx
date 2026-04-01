import type React from 'react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../hooks';
import { SettingsAlert } from '../components/settings';

declare global {
  interface Window {
    turnstile?: {
      render: (
        container: HTMLElement,
        options: {
          sitekey: string;
          callback: (token: string) => void;
          'expired-callback'?: () => void;
          'error-callback'?: () => void;
          theme?: 'light' | 'dark' | 'auto';
        }
      ) => string | number;
      remove?: (widgetId: string | number) => void;
      reset?: (widgetId?: string | number) => void;
    };
  }
}

const LoginPage: React.FC = () => {
  const {
    login,
    fixedUsername,
    humanVerificationEnabled,
    humanVerificationProvider,
    turnstileSiteKey,
  } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawRedirect = searchParams.get('redirect') ?? '';
  const redirect =
    rawRedirect.startsWith('/') && !rawRedirect.startsWith('//') ? rawRedirect : '/';

  const [username, setUsername] = useState(fixedUsername ?? 'admin');
  const [password, setPassword] = useState('');
  const [humanToken, setHumanToken] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const turnstileContainerRef = useRef<HTMLDivElement | null>(null);
  const turnstileWidgetIdRef = useRef<string | number | null>(null);

  useEffect(() => {
    if (fixedUsername) {
      setUsername(fixedUsername);
    }
  }, [fixedUsername]);

  useEffect(() => {
    if (!humanVerificationEnabled || humanVerificationProvider !== 'turnstile' || !turnstileSiteKey) {
      return undefined;
    }

    let cancelled = false;
    const scriptId = 'cf-turnstile-script';

    const mountWidget = () => {
      if (cancelled || !turnstileContainerRef.current || !window.turnstile) return;
      if (turnstileWidgetIdRef.current != null && window.turnstile.remove) {
        window.turnstile.remove(turnstileWidgetIdRef.current);
      }
      turnstileContainerRef.current.innerHTML = '';
      turnstileWidgetIdRef.current = window.turnstile.render(turnstileContainerRef.current, {
        sitekey: turnstileSiteKey,
        callback: (token: string) => {
          setHumanToken(token);
          setError((prev) => (prev === '请先完成人机验证' ? null : prev));
        },
        'expired-callback': () => setHumanToken(null),
        'error-callback': () => setHumanToken(null),
        theme: 'dark',
      });
    };

    const existingScript = document.getElementById(scriptId) as HTMLScriptElement | null;
    if (existingScript && window.turnstile) {
      mountWidget();
    } else if (existingScript) {
      existingScript.addEventListener('load', mountWidget, { once: true });
    } else if (!existingScript) {
      const script = document.createElement('script');
      script.id = scriptId;
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      script.async = true;
      script.defer = true;
      script.onload = mountWidget;
      document.body.appendChild(script);
    }

    return () => {
      cancelled = true;
      if (turnstileWidgetIdRef.current != null && window.turnstile?.remove) {
        window.turnstile.remove(turnstileWidgetIdRef.current);
        turnstileWidgetIdRef.current = null;
      }
    };
  }, [humanVerificationEnabled, humanVerificationProvider, turnstileSiteKey]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (humanVerificationEnabled && !humanToken) {
      setError('请先完成人机验证');
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await login(username, password, humanToken ?? undefined);
      if (result.success) {
        navigate(redirect, { replace: true });
      } else {
        setError(result.error ?? '登录失败');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-base px-4">
      <div className="w-full max-w-sm rounded-2xl border border-white/8 bg-card/80 p-6 backdrop-blur-sm">
        <h1 className="mb-2 text-xl font-semibold text-white">管理员登录</h1>
        <p className="mb-6 text-sm text-secondary">
          请输入固定管理员账号和密码后继续访问。
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="mb-1 block text-sm font-medium text-secondary">
              用户名
            </label>
            <input
              id="username"
              type="text"
              className="input-terminal"
              placeholder="输入用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isSubmitting}
              autoFocus
              autoComplete="username"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-secondary">
              密码
            </label>
            <input
              id="password"
              type="password"
              className="input-terminal"
              placeholder="输入密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isSubmitting}
              autoComplete="current-password"
            />
          </div>

          {humanVerificationEnabled && humanVerificationProvider === 'turnstile' ? (
            <div>
              <p className="mb-2 block text-sm font-medium text-secondary">真人验证</p>
              <div ref={turnstileContainerRef} className="min-h-[65px]" />
            </div>
          ) : null}

          {error ? (
            <SettingsAlert
              title="登录失败"
              message={error}
              variant="error"
              className="!mt-3"
            />
          ) : null}

          <button
            type="submit"
            className="btn-primary w-full"
            disabled={isSubmitting || !username.trim() || !password.trim() || (humanVerificationEnabled && !humanToken)}
          >
            {isSubmitting ? '登录中...' : '登录'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
