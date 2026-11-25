/**
 * Web link of a git clone URL, the usual rule of git hosting servers (GitHub, GitLab, Gitea, Bitbucket):
 *   git@host:group/repo.git          -> https://host/group/repo
 *   ssh://git@host:2222/group/repo.git -> https://host/group/repo   (user and port dropped)
 *   https://host/group/repo.git      -> https://host/group/repo
 * A leading "ssh." of the host is dropped, for servers with a separate ssh host name
 * (ssh.example.com for the web server example.com). This is a guess: the link can be wrong, the URL shown is not
 * changed. Anything else is returned unchanged.
 */
export function gitWebUrl(url) {
  const v = (url ?? '').trim();
  let m = v.match(/^ssh:\/\/(?:[^@/]+@)?([^/:]+)(?::\d+)?\/(.+)$/)   // ssh://[user@]host[:port]/path
       || v.match(/^(?:[^@/]+@)?([^/:]+):(?!\/)(.+)$/);            // [user@]host:path (scp syntax)
  if (m) {
    const host = m[1].replace(/^ssh\./, '');
    return `https://${host}/${m[2].replace(/\.git\/?$/, '')}`;
  }
  m = v.match(/^(https?:\/\/.+?)(?:\.git)?\/?$/);
  return m ? m[1] : url;
}
