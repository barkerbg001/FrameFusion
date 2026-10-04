import { ROUTES, studio, type AgentRegistry, type Readiness, type Route, type SpecialistInfo } from '../api.ts'
import { avatar, PERSONALITIES, PERSONALITY_IDS, personality } from '../avatars.ts'
import { h, icon, replace } from '../dom.ts'
import { refreshReadiness, state } from '../state.ts'
import { errorState, focusHeading, loadingState, pageHeader } from './common.ts'

const SPECIALIST_ICONS: Record<string, string> = {
  research: 'research',
  script: 'script',
  visual: 'image',
  ideas: 'idea',
  music_composer: 'music',
}

export function agentsView(outlet: HTMLElement): () => void {
  const body = h('div', { class: 'agents-body' })
  replace(
    outlet,
    h(
      'div',
      { class: 'page page-agents' },
      pageHeader(
        'Agents',
        'One orchestrator works with you and hands each step to a specialist. Specialists report back to the orchestrator; they never delegate to each other.',
        [h('a', { class: 'button', href: '#/settings' }, icon('settings', 16), 'Personality and models')],
      ),
      body,
    ),
  )
  focusHeading(outlet)

  async function load(): Promise<void> {
    replace(body, loadingState('Loading agents…'))
    try {
      const [registry, readiness] = await Promise.all([studio.agents(), refreshReadiness()])
      replace(body, orchestratorSection(registry, readiness), specialistsSection(registry.specialists, readiness), servicesSection(registry))
    } catch (error) {
      replace(body, errorState(error, () => void load()))
    }
  }

  void load()
  return () => {}
}

function routeLine(readiness: Readiness | undefined): HTMLElement {
  if (readiness?.ready) {
    return h(
      'p',
      { class: 'agent-route' },
      h('span', { class: 'status-dot ok', 'aria-hidden': 'true' }),
      h('span', null, `${readiness.provider_label} · `),
      h('code', null, readiness.model ?? ''),
      h('span', { class: 'muted' }, readiness.source === 'override' ? ' (route override)' : ' (default model)'),
    )
  }
  return h(
    'p',
    { class: 'agent-route warn' },
    h('span', { class: 'status-dot warn', 'aria-hidden': 'true' }),
    h('span', null, readiness?.problem ?? 'Not set up.'),
    ' ',
    h('a', { class: 'link', href: '#/settings' }, 'Fix in Settings'),
  )
}

function orchestratorSection(registry: AgentRegistry, readiness: Record<Route, Readiness>): HTMLElement {
  const current = personality(state.app?.personality)
  const ready = ROUTES.every((route) => readiness[route].ready)
  return h(
    'section',
    { class: `persona-section tone-${current.tone}`, 'aria-labelledby': 'orchestrator-title' },
    h(
      'div',
      { class: 'persona-hero' },
      avatar(current.id, { size: 'xl', portrait: true, state: ready ? 'idle' : 'setup' }),
      h(
        'div',
        null,
        h('h2', { id: 'orchestrator-title' }, registry.orchestrator.name, h('span', { class: 'role-tag' }, `Default personality: ${current.name}`)),
        h('p', null, registry.orchestrator.role),
        routeLine(readiness[registry.orchestrator.route]),
        h('p', { class: 'muted' }, 'Tools: ', registry.orchestrator.tools.flatMap((tool, i) => [i ? ', ' : '', h('code', null, tool)])),
      ),
    ),
    h(
      'ul',
      { class: 'role-grid personality-grid' },
      PERSONALITY_IDS.map((id) => {
        const info = PERSONALITIES[id]
        return h(
          'li',
          { class: `role-card tone-${info.tone}${id === current.id ? ' is-current' : ''}` },
          h('div', { class: 'role-card-head' }, avatar(id, { size: 'sm' }), h('h3', null, info.name)),
          h('p', { class: 'muted' }, info.tagline),
          h('p', null, info.summary),
          id === current.id ? h('span', { class: 'chip' }, icon('check', 14), 'Default') : null,
        )
      }),
    ),
    h('p', { class: 'field-hint' }, 'Both personalities are the same orchestrator with the same specialists, tools, models and permissions. Only the voice changes.'),
  )
}

function specialistsSection(specialists: SpecialistInfo[], readiness: Record<Route, Readiness>): HTMLElement {
  return h(
    'section',
    { class: 'agents-section', 'aria-labelledby': 'specialists-title' },
    h('h2', { id: 'specialists-title' }, 'Specialists'),
    h('p', { class: 'muted' }, 'Each specialist does one production stage when the orchestrator asks, using its own tools, and returns an artifact the orchestrator checks.'),
    h(
      'ul',
      { class: 'role-grid' },
      specialists.map((specialist) =>
        h(
          'li',
          { class: 'role-card' },
          h('div', { class: 'role-card-head' }, h('span', { class: 'route-icon', 'aria-hidden': 'true' }, icon(SPECIALIST_ICONS[specialist.id] ?? 'sparkle', 18)), h('h3', null, specialist.name)),
          h('p', { class: 'muted' }, specialist.role),
          h(
            'dl',
            { class: 'role-facts' },
            h('dt', null, 'Produces'),
            h('dd', null, specialist.produces),
            h('dt', null, 'Tools'),
            h('dd', null, specialist.tools.length ? specialist.tools.flatMap((tool, i) => [i ? ', ' : '', h('code', null, tool)]) : 'None (deterministic step)'),
            h('dt', null, 'Model route'),
            h('dd', null, readiness[specialist.route]?.ready ? specialist.route_label : `${specialist.route_label} (not set up)`),
            h('dt', null, 'Reports to'),
            h('dd', null, 'Orchestrator'),
          ),
        ),
      ),
    ),
  )
}

function servicesSection(registry: AgentRegistry): HTMLElement {
  return h(
    'section',
    { class: 'agents-section', 'aria-labelledby': 'services-title' },
    h('h2', { id: 'services-title' }, 'Services'),
    h('p', { class: 'muted' }, 'Deterministic tools the specialists call. They do not plan or talk to you.'),
    h(
      'ul',
      { class: 'role-duties' },
      registry.services.map((service) => h('li', null, h('strong', null, service.name), ` · ${service.role}`)),
    ),
  )
}
