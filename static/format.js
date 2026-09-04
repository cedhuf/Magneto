/* Shared by every page. These four were written twice, once per template, and
   had already drifted into two names for the same thing. */

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : s;
  return d.innerHTML;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function fmtDate(d) {
  // yt-dlp gives YYYYMMDD as a string.
  if (!d || d.length !== 8) return '';
  return `${+d.slice(6)} ${MONTHS[+d.slice(4, 6) - 1]} ${d.slice(0, 4)}`;
}

function fmtDur(s) {
  if (!s) return '';
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

function fmtSize(n) {
  if (!n) return '';
  return n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.round(n / 1e6)} MB`;
}

function friendlyError(err) {
  if (!err) return '';
  if (err.includes('Unsupported URL')) return 'This URL is not supported';
  if (err.includes('Video unavailable')) return 'Video is unavailable or private';
  if (err.includes('Private video')) return 'This video is private';
  if (err.includes('HTTP Error 403')) return 'Access denied by the platform';
  if (err.includes('HTTP Error 404')) return 'Not found';
  if (err.includes('copyright')) return 'Blocked due to copyright';
  if (err.includes('geo')) return 'Not available in your region';
  if (err.includes('timed out') || err.includes('Timed out')) return 'Timed out, try again';
  if (err.includes('network') || err.includes('Network')) return 'Network error';
  return err.length > 80 ? err.slice(0, 80) + '...' : err;
}
