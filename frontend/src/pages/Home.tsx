import { useNavigate } from 'react-router-dom'
import { homeKpi, homeRecipes, homeDeals, img } from '../lib/data'

export default function Home() {
  const nav = useNavigate()
  return (
    <div>
      {/* 히어로 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 1fr', minHeight: 300, marginBottom: 24, border: '1px solid #E6E6E6', overflow: 'hidden' }} className="max-[720px]:!grid-cols-1">
        <div style={{ background: '#1A1A1A', color: '#fff', padding: '48px 44px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ display: 'inline-flex', alignSelf: 'flex-start', alignItems: 'center', gap: 7, background: '#1FA463', color: '#fff', fontSize: 12.5, fontWeight: 800, padding: '6px 12px', marginBottom: 22 }}>
            7월 식비 · 아직 여유 있어요
          </div>
          <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: '-1px', lineHeight: 1.3 }}>
            냉장고를 털어 <span style={{ color: '#7FD6A2' }}>27,000원</span>
            <br />
            아꼈어요
          </div>
          <div style={{ fontSize: 15, color: 'rgba(255,255,255,.62)', marginTop: 14, lineHeight: 1.6 }}>
            이번 주도 있는 재료로 알뜰하게.
            <br />
            오늘 뭘 해먹을지 골라볼까요?
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 28, flexWrap: 'wrap' }}>
            <button onClick={() => nav('/meal')} style={{ padding: '14px 26px', border: 'none', background: '#1FA463', color: '#fff', fontSize: 15, fontWeight: 800, cursor: 'pointer' }}>
              오늘 뭐 해먹지?
            </button>
            <button onClick={() => nav('/fridge')} style={{ padding: '14px 22px', border: '1px solid rgba(255,255,255,.28)', background: 'none', color: '#fff', fontSize: 15, fontWeight: 700, cursor: 'pointer' }}>
              내 냉장고 보기
            </button>
          </div>
        </div>
        <div style={{ position: 'relative', background: '#F0F0F0 center/cover no-repeat', backgroundImage: 'url("/icons/home-hero.jpg")' }}>
          <div style={{ position: 'absolute', left: 20, bottom: 20, background: 'rgba(26,26,26,.82)', color: '#fff', padding: '11px 16px', backdropFilter: 'blur(4px)' }}>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,.6)', fontWeight: 600 }}>이번 주 절약률</div>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.5px' }}>
              23% <span style={{ fontSize: 12, color: '#7FD6A2', fontWeight: 700 }}>▲ 지난주 대비</span>
            </div>
          </div>
        </div>
      </div>

      {/* KPI 4 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', border: '1px solid #E6E6E6', marginBottom: 34, overflow: 'hidden' }}>
        {homeKpi.map((s, i) => (
          <div
            key={s.k}
            onClick={s.to ? () => nav(s.to!) : undefined}
            style={{ padding: '18px 20px', borderRight: i < homeKpi.length - 1 ? '1px solid #E6E6E6' : 'none', cursor: s.to ? 'pointer' : 'default' }}
          >
            <div style={{ fontSize: 12, color: '#9A9A9A', marginBottom: 5 }}>{s.k}</div>
            <div className="num" style={{ fontSize: 21, fontWeight: 800, color: s.color ?? '#1A1A1A' }}>{s.v}</div>
            <div style={{ fontSize: 11, color: s.subColor ?? '#9A9A9A', marginTop: 3 }}>{s.sub}</div>
          </div>
        ))}
      </div>

      {/* 냉장고 재료로 만드는 한 끼 */}
      <SectionHead title="냉장고 재료로 만드는 한 끼" sub="임박 재료 · 남은 예산까지 고려한 추천이에요" more="더보기 ›" onMore={() => nav('/meal')} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 20, marginBottom: 44 }}>
        {homeRecipes.map((r) => (
          <div key={r.name} onClick={() => nav('/recipes/1')} style={{ cursor: 'pointer' }}>
            <div style={{ aspectRatio: '1', position: 'relative', overflow: 'hidden', background: `#F0F0F0 center/cover no-repeat url("${img(r.p)}")` }}>
              <span style={{ position: 'absolute', left: 8, bottom: 8, background: '#1FA463', color: '#fff', fontSize: 10.5, fontWeight: 700, padding: '3px 7px' }}>새벽배송</span>
            </div>
            <div style={{ marginTop: 11 }}>
              <div style={{ fontSize: 12, color: '#9A9A9A' }}>{r.tag}</div>
              <div style={{ fontSize: 14, fontWeight: 600, marginTop: 3, lineHeight: 1.4 }}>{r.name}</div>
              <div className="num" style={{ fontSize: 15, fontWeight: 800, marginTop: 4, color: r.free ? '#15B76E' : '#1FA463' }}>{r.add}</div>
            </div>
          </div>
        ))}
      </div>

      {/* 오늘의 특가 · 시세 */}
      <SectionHead title="오늘의 특가 · 시세" sub="평균가보다 저렴할 때 담아두세요" more="더보기 ›" onMore={() => nav('/hotdeal')} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(180px,1fr))', gap: 20 }}>
        {homeDeals.map((d) => (
          <div key={d.name} onClick={() => nav('/cart')} style={{ cursor: 'pointer' }}>
            <div style={{ aspectRatio: '1', position: 'relative', overflow: 'hidden', background: `#F0F0F0 center/cover no-repeat url("${img(d.p)}")` }}>
              <span style={{ position: 'absolute', left: 8, bottom: 8, background: '#1FA463', color: '#fff', fontSize: 10.5, fontWeight: 700, padding: '3px 7px' }}>새벽배송</span>
            </div>
            <div style={{ marginTop: 11 }}>
              <div style={{ fontSize: 12, color: '#9A9A9A' }}>{d.brand}</div>
              <div style={{ fontSize: 14, fontWeight: 600, marginTop: 3, lineHeight: 1.4 }}>{d.name}</div>
              <div style={{ marginTop: 5, display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span className="num" style={{ fontSize: 15, fontWeight: 800, color: '#F04452' }}>{d.pct}%</span>
                <span className="num" style={{ fontSize: 15, fontWeight: 800 }}>{d.price}원</span>
              </div>
              <div className="num" style={{ fontSize: 11.5, color: '#9A9A9A', textDecoration: 'line-through' }}>{d.orig}원</div>
              <div style={{ fontSize: 11, color: '#9A9A9A', marginTop: 2 }}>후기 {d.review}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function SectionHead({ title, sub, more, onMore }: { title: string; sub?: string; more?: string; onMore?: () => void }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>{title}</h2>
        {sub && <p style={{ fontSize: 13, color: '#9A9A9A', margin: '5px 0 0' }}>{sub}</p>}
      </div>
      {more && (
        <span onClick={onMore} style={{ fontSize: 13, color: '#5E5E5E', cursor: 'pointer', whiteSpace: 'nowrap' }}>
          {more}
        </span>
      )}
    </div>
  )
}
