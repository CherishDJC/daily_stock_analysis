import type React from 'react';
import { useState } from 'react';
import {
  clearPageStateCache,
  clearPageStateCacheByKey,
  PAGE_STATE_STORAGE_KEYS,
  PAGE_STATE_STORAGE_LABELS,
} from '../../utils/persist';
import { SettingsAlert } from './SettingsAlert';

export const PageStateCacheCard: React.FC = () => {
  const [message, setMessage] = useState<string | null>(null);

  const handleClearAll = () => {
    const confirmed = window.confirm('清除首页、选股页、看盘页的全部页面缓存并刷新当前页面？');
    if (!confirmed) return;

    try {
      clearPageStateCache();
      setMessage('全部页面缓存已清除，正在刷新...');
      window.setTimeout(() => {
        window.location.reload();
      }, 250);
    } catch {
      setMessage('页面缓存清除失败，请重试');
    }
  };

  const handleClearSingle = (key: (typeof PAGE_STATE_STORAGE_KEYS)[number]) => {
    const label = PAGE_STATE_STORAGE_LABELS[key];
    const confirmed = window.confirm(`清除“${label}”的页面缓存并刷新当前页面？`);
    if (!confirmed) return;

    try {
      clearPageStateCacheByKey(key);
      setMessage(`${label}缓存已清除，正在刷新...`);
      window.setTimeout(() => {
        window.location.reload();
      }, 250);
    } catch {
      setMessage(`${label}缓存清除失败，请重试`);
    }
  };

  return (
    <div className="rounded-xl border border-white/8 bg-elevated/50 p-4">
      <div className="mb-2 flex items-center gap-2">
        <label className="text-sm font-semibold text-white">页面缓存</label>
      </div>
      <p className="mb-3 text-xs text-muted">
        清除首页、选股页、看盘页的会话级页面缓存。适用于切换模块后想回到完全干净的状态。
      </p>

      {message ? (
        <SettingsAlert
          title={message.includes('失败') ? '清除失败' : '操作提示'}
          message={message}
          variant={message.includes('失败') ? 'error' : 'success'}
          className="mb-3"
        />
      ) : null}

      <button
        type="button"
        className="btn-secondary"
        onClick={handleClearAll}
      >
        清除全部缓存并刷新
      </button>

      <div className="mt-3 flex flex-wrap gap-2">
        {PAGE_STATE_STORAGE_KEYS.map((key) => (
          <button
            key={key}
            type="button"
            className="btn-secondary !px-3 !py-2 text-xs"
            onClick={() => handleClearSingle(key)}
          >
            清除{PAGE_STATE_STORAGE_LABELS[key]}
          </button>
        ))}
      </div>
    </div>
  );
};
