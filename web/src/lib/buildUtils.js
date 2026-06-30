/**
 * Shared build helpers — ported from build.service.ts and build-table.ts.
 */

// Maps buildstate → Bootstrap Icons class (bi-*)
// Mirrors buildicon() from the Angular service.
export function buildIcon(buildstate) {
  switch (buildstate) {
    case 'new':
    case 'scheduled':       return 'bi-clock';
    case 'needs_build':     return 'bi-three-dots';
    case 'building':        return 'bi-arrow-repeat rotating text-primary';
    case 'needs_publish':   return 'bi-git';
    case 'publishing':      return 'bi-upload text-primary';
    case 'publish_failed':  return 'bi-upload text-danger';
    case 'successful':
    case 'already_exists':
    case 'nothing_done':    return 'bi-check-lg text-success';
    case 'build_failed':
    case 'already_failed':  return 'bi-x-lg text-danger';
    default:                return 'bi-question';
  }
}

// Maps buildtype → Bootstrap Icons class
export function buildTypeIcon(buildtype) {
  switch (buildtype) {
    case 'build':                 return 'bi-box-arrow-up-right';
    case 'source':                return 'bi-journals';
    case 'deb':                   return 'bi-file-earmark-zip';
    case 'mirror':                return 'bi-folder-symlink';
    case 'debootstrap':           return 'bi-tree';
    case 'chroot':                return 'bi-diagram-3';
    case 'copy_projectversion':   return 'bi-copy';
    case 'delete_projectversion': return 'bi-trash';
    case 'cleanup':               return 'bi-brush';
    default:                      return 'bi-question';
  }
}

// Maps buildtype → tooltip label
export function buildTypeLabel(buildtype) {
  switch (buildtype) {
    case 'build':                 return 'Build Task';
    case 'source':                return 'Source Package';
    case 'deb':                   return 'Debian Package';
    case 'mirror':                return 'Debian Mirror';
    case 'debootstrap':           return 'Debootstrap Archive';
    case 'chroot':                return 'Schroot Archive';
    case 'copy_projectversion':   return 'Copy Projectversion';
    case 'delete_projectversion': return 'Delete Projectversion';
    case 'cleanup':               return 'Cleanup Task';
    default:                      return buildtype;
  }
}

// Row label shown in the sourcename column — mirrors build-table.html logic.
export function buildLabel(build) {
  switch (build.buildtype) {
    case 'build':                 return { text: build.sourcename, bold: true };
    case 'source':                return { text: build.version, bold: true };
    case 'deb':                   return { text: build.buildvariant?.name, bold: false };
    case 'mirror':                return { text: `${build.sourcename}/${build.version}`, bold: true,
                                           suffix: build.architectures ? ` (${build.architectures.join(', ')})` : '' };
    case 'chroot':                return { text: build.architecture, bold: true };
    case 'cleanup':
    case 'copy_projectversion':
    case 'delete_projectversion': return { text: build.sourcename, bold: true };
    default:                      return { text: build.sourcename, bold: false };
  }
}

// Row background — mirrors getRowBackground()
export function rowBackground(buildtype) {
  switch (buildtype) {
    case 'build':
    case 'cleanup':
    case 'copy_projectversion':
    case 'delete_projectversion':
    case 'mirror':
      return '#F5F5F5';
    default:
      return undefined;
  }
}

// Duration string — mirrors duration() in build-table.ts
export function formatDuration(build) {
  const terminalStates = ['successful', 'build_failed', 'already_exists', 'nothing_done', 'publish_failed'];
  if (build.endstamp && build.startstamp && terminalStates.includes(build.buildstate)) {
    const interval = (new Date(build.endstamp) - new Date(build.startstamp)) / 1000;
    const hrs  = Math.floor(interval / 3600);
    const mins = Math.floor((interval - hrs * 3600) / 60);
    let secs   = String(Math.floor(interval % 60));
    let t = '';
    if (hrs  > 0) t += `${hrs}h `;
    if (mins > 0) t += `${mins}m `;
    if (hrs > 0 || mins > 0) secs = secs.padStart(2, '0');
    return t + `${secs}s`;
  }
  return null;
}

// Start time label — mirrors startTime() in build-table.ts
export function formatStartTime(build, showFull = false) {
  if (!build.startstamp) return null;
  const ts = new Date(build.startstamp);
  if (showFull) return ts.toString();

  const now  = new Date();
  const pad  = n => String(n).padStart(2, '0');
  const hms  = `${pad(ts.getHours())}:${pad(ts.getMinutes())}:${pad(ts.getSeconds())}`;
  const hm   = `${pad(ts.getHours())}:${pad(ts.getMinutes())}`;
  const mm   = `${pad(ts.getMonth() + 1)}-${pad(ts.getDate())}`;

  const sameDay  = ts.toDateString() === now.toDateString();
  const daysDiff = Math.round((now - ts) / 86400000);

  if (sameDay)        return hms;
  if (daysDiff === 1) return `yesterday, ${hm}`;
  if (daysDiff < 15)  return `${daysDiff} days ago, ${hm}`;
  if (ts.getFullYear() === now.getFullYear()) return `${mm} ${hm}`;
  return `${ts.getFullYear()}-${mm} ${hm}`;
}

// Build state filter groups — mirrors mergeBuildStates()
export const BUILD_STATE_GROUPS = [
  { label: 'Successful',  value: 'successful/already_exists/nothing_done',  icon: 'bi-check-lg text-success' },
  { label: 'Publishing',  value: 'publishing/publish_failed',               icon: 'bi-upload' },
  { label: 'Pending',     value: 'new/scheduled',                           icon: 'bi-clock' },
  { label: 'Failed',      value: 'build_failed/already_failed',             icon: 'bi-x-lg text-danger' },
  { label: 'Building',    value: 'building',                                icon: 'bi-arrow-repeat rotating' },
  { label: 'Needs build', value: 'needs_build',                             icon: 'bi-three-dots' },
];

export function expandBuildStateGroup(value) {
  switch (value) {
    case 'successful/already_exists/nothing_done': return ['successful', 'already_exists', 'nothing_done'];
    case 'publishing/publish_failed':              return ['publishing', 'publish_failed'];
    case 'new/scheduled':                          return ['new', 'scheduled'];
    case 'build_failed/already_failed':            return ['build_failed', 'already_failed'];
    default:                                       return [value];
  }
}
