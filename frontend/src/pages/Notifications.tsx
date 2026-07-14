import { useNavigate } from 'react-router-dom'

const list = [
  { to: '/fridge', title: '두부 유통기한 임박', desc: '내일 만료 · 두부 레시피 3개 추천', time: '1시간 전', color: '#F04452' },
  { to: '/hotdeal', title: '삼겹살 최저가 알림!', desc: '마켓컬리 100g 1,290원 (평균 대비 30%↓)', time: '3시간 전', color: '#F26419' },
  { to: '/recipebook', title: '박요리님이 레시피북을 공유했어요', desc: '"자취생 일주일 식단" · 7개 레시피', time: '5시간 전' },
  { to: '/expense', title: '오늘 식비 11,200원', desc: '이번 주 예산의 58% 사용', time: '어제' },
  { to: '/hotdeal', title: '지마켓 타임딜 업데이트', desc: '식품 핫딜 12개 · 20시 기준', time: '어제' },
]

export default function Notifications() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>알림</h1>
        <span style={{ fontSize: 13, color: '#F26419', fontWeight: 600, cursor: 'pointer' }}>모두 읽음</span>
      </div>
      <div style={{ maxWidth: 640, background: '#fff', border: '1px solid #E6E6E6', padding: '8px 20px' }}>
        {list.map((n, i) => (
          <div key={i} onClick={() => nav(n.to)} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 0', borderBottom: i < list.length - 1 ? '1px solid #EFEFEF' : 'none', cursor: 'pointer' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: n.color ?? '#17264A' }}>{n.title}</div>
              <div style={{ fontSize: 12, color: '#9A9A9A' }}>{n.desc}</div>
            </div>
            <span style={{ fontSize: 11, color: '#9A9A9A', whiteSpace: 'nowrap' }}>{n.time}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
