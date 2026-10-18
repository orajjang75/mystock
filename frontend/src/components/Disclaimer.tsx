export const DISCLAIMER_TEXT = '지표 기반 참고 정보이며 수익을 보장하지 않는다'

/** PRD 10장: shown on every screen, always. */
export function Disclaimer() {
  return (
    <div className="disclaimer" role="note">
      {DISCLAIMER_TEXT}
    </div>
  )
}
