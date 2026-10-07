import { pad } from '../copy'

const THIS_MONTH = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(
  new Date(),
)

export function Masthead({ issue, onHome }: { issue: number | null; onHome: () => void }) {
  return (
    <header className="masthead">
      <div className="masthead__rail">
        <span>{THIS_MONTH}</span>
        <span>{issue ? `Issue No. ${pad(issue, 3)}` : 'A listening guide'}</span>
      </div>
      <h1 className="masthead__title">
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault()
            onHome()
          }}
        >
          Sideways
        </a>
      </h1>
      <p className="masthead__dek">Music one step over from what you already love.</p>
    </header>
  )
}
