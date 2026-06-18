import { DEFAULT_MINIAPP_CONTENT } from '../appShared.jsx'

export default function InfoScreen({ miniappContent }) {
  const activeInfoLinks = miniappContent?.info_links?.length
    ? miniappContent.info_links
    : DEFAULT_MINIAPP_CONTENT.info_links

  return (
    <section className="screen-block">
      <h1 className="screen-title">Информация</h1>
      <div className="info-links">
        {activeInfoLinks.map((item) => (
          <a key={item.key} href={item.url} target="_blank" rel="noreferrer" className="info-link-card">
            <span>{item.title}</span>
            <span className="link-arrow">→</span>
          </a>
        ))}
      </div>
    </section>
  )
}
