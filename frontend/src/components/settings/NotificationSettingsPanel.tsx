import { useState } from 'react'

// 알림 유형 on/off. 현재는 기기별(localStorage) 설정 — 서버 fan-out 연동은 후속(notify 서비스).
const TYPES = [
  { key: 'LOW_PRICE', label: '최저가 알림', desc: '관심 재료가 싸지면 알려드려요' },
  { key: 'EXPIRING', label: '소비기한 임박', desc: '냉장고 재료가 임박하면 알려드려요' },
  { key: 'HOTDEAL', label: '핫딜·마감특가', desc: '오후 5시 마감특가 오픈을 알려드려요' },
  { key: 'BUDGET', label: '예산 경고', desc: '예산을 초과할 것 같으면 알려드려요' },
] as const

const STORAGE_KEY = 'notif_prefs'
const DEFAULTS: Record<string, boolean> = { LOW_PRICE: true, EXPIRING: true, HOTDEAL: true, BUDGET: true }

function load(): Record<string, boolean> {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') }
  } catch {
    return { ...DEFAULTS }
  }
}

export default function NotificationSettingsPanel() {
  const [prefs, setPrefs] = useState<Record<string, boolean>>(load)

  const toggle = (key: string) => {
    const next = { ...prefs, [key]: !prefs[key] }
    setPrefs(next)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: '#5E5E5E', margin: '0 0 16px', lineHeight: 1.6 }}>
        받고 싶은 알림을 켜고 끌 수 있어요. <span style={{ color: '#9A9A9A' }}>(이 기기에 저장돼요)</span>
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {TYPES.map((t) => (
          <div key={t.key} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 4px', borderTop: '1px solid #EFEFEF' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#17264A' }}>{t.label}</div>
              <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 2 }}>{t.desc}</div>
            </div>
            <button
              onClick={() => toggle(t.key)}
              role="switch"
              aria-checked={prefs[t.key]}
              aria-label={t.label}
              style={{ position: 'relative', width: 46, height: 26, flexShrink: 0, borderRadius: 13, border: 'none', cursor: 'pointer', background: prefs[t.key] ? '#F26419' : '#D6D6D6', transition: 'background .2s' }}
            >
              <span style={{ position: 'absolute', top: 3, left: prefs[t.key] ? 23 : 3, width: 20, height: 20, borderRadius: '50%', background: '#fff', transition: 'left .2s', boxShadow: '0 1px 3px rgba(0,0,0,.25)' }} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
