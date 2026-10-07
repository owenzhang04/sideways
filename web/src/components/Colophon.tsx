export function Colophon() {
  return (
    <footer className="colophon">
      <h4 className="kicker">How this works</h4>
      <ol className="colophon__steps">
        <li>
          <strong>Neighbors.</strong> For each seed, Sideways asks ListenBrainz which artists its
          listeners play in the same sessions, and asks Deezer for its related artists. When both
          agree on a pair, that link counts for more.
        </li>
        <li>
          <strong>A walk.</strong> Those links form a graph. A personalized PageRank walk starts
          from your seeds; artists the walk keeps landing on rank higher. Artists you set aside
          push their neighbors down.
        </li>
        <li>
          <strong>The edit.</strong> Familiar or adventurous tilts the list by Deezer fan counts.
          Picks with overlapping genre tags are spread apart so the list doesn't repeat itself.
        </li>
      </ol>
      <p className="colophon__credits">
        Similarity from <a href="https://listenbrainz.org">ListenBrainz</a> and{' '}
        <a href="https://www.deezer.com">Deezer</a>. Tags from{' '}
        <a href="https://musicbrainz.org">MusicBrainz</a>. Previews courtesy of Deezer. Not
        affiliated with Spotify or Deezer.
      </p>
    </footer>
  )
}
