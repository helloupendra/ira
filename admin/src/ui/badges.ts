// One place for the colour of a status word, so every screen agrees.
export function actionBadge(status: string): string {
  switch (status) {
    case 'pending':
      return 'badge badge-warn';
    case 'executing':
      return 'badge badge-accent';
    case 'executed':
      return 'badge badge-ok';
    case 'failed':
      return 'badge badge-danger';
    case 'unknown':
      return 'badge badge-warn';
    default:
      return 'badge badge-muted';
  }
}

export function outcomeBadge(outcome: string): string {
  switch (outcome) {
    case 'executed':
    case 'pin_set':
      return 'badge badge-ok';
    case 'proposed':
      return 'badge badge-accent';
    case 'unknown':
      return 'badge badge-warn';
    case 'wrong_pin':
    case 'locked':
    case 'failed':
    case 'not_allowed':
      return 'badge badge-danger';
    default:
      return 'badge badge-muted';
  }
}

export function onOffBadge(on: boolean): string {
  return on ? 'badge badge-ok' : 'badge badge-muted';
}

export function inviteBadge(state: string): string {
  switch (state) {
    case 'pending':
      return 'badge badge-warn';
    case 'used':
      return 'badge badge-ok';
    default:
      return 'badge badge-muted';
  }
}
