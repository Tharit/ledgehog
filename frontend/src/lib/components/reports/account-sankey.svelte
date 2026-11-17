<script lang="ts">
	import { Chart, getChartContext, Link, Svg } from 'layerchart';
	import { Sankey } from 'layerchart/graph';
	import * as ChartUi from '#lib/components/ui/chart/index.js';
	import { formatMoney } from '#lib/format/index.js';
	import {
		layerPlan,
		LINK_OPACITY,
		STAYED_OPACITY,
		type AccountSankey,
		type SankeyLink,
		type SankeyNode
	} from '#lib/reports/sankey.js';
	import { dimensionVars } from '#lib/theme/dimensions.js';
	import { iconFor } from '#lib/theme/icons.js';
	import FigureTooltip from './figure-tooltip.svelte';
	import TipBridge from './tip-bridge.svelte';
	import type { Tip } from './figure-tooltip.svelte';

	// *By account*'s sankey (design §8): four fixed columns (income side, accounts that received,
	// accounts that paid, expense side), a category a slim bar in its colour, an account a wider
	// block in its colour with its icon and name, a link its category's colour at 35 %, a transfer
	// stone at 35 %, the money that stayed in an account stone at 20 %. The layout is layerchart's
	// Sankey with every node's layer given by its column. A link with a ledger filter is a link to
	// it. The table beside the chart is the data; a link's tooltip names what it is, its two
	// ends and its amount.
	let { model, locale = 'en' }: { model: AccountSankey; locale?: string } = $props();

	const NODE_WIDTH = 20;
	const BAR_WIDTH = 6;
	const LABEL_ROOM = 128;
	const ROW_HEIGHT = 34;

	// the layout writes into what it is given and replaces the keys of a link's ends by nodes
	const plan = $derived(layerPlan(model));
	const data = $derived({
		nodes: model.nodes.map((n) => ({ ...n, layer: plan.layers[n.column] })),
		links: [
			...model.links.map((l) => ({ ...l })),
			...plan.spine.map((s) => ({ ...s, key: `${s.source}>${s.target}:spine`, value: 0 }))
		]
	});
	const height = $derived(Math.max(288, model.fullest * ROW_HEIGHT + 32));

	type Laid = SankeyNode & { x0: number; x1: number; y0: number; y1: number };
	type LaidLink = SankeyLink & { source: Laid; target: Laid; width: number };

	// links leave and enter a node in the order of the nodes at their other ends
	type Ends = { source: { order?: number }; target: { order?: number } };
	const byEnds = (a: Ends, b: Ends) =>
		(a.target.order ?? 0) - (b.target.order ?? 0) || (a.source.order ?? 0) - (b.source.order ?? 0);

	const money = (minor: number) => formatMoney(minor, model.currency, { locale });

	function describe(link: SankeyLink): Tip {
		if (link.stayed) {
			return {
				title: link.label,
				rows: [
					{ label: 'Received', value: money(link.stayed.received) },
					{ label: 'Transferred out', value: money(-link.stayed.transferredOut) },
					{ label: 'Stayed', value: money(link.value) }
				]
			};
		}
		return {
			title: link.label,
			rows: [
				{
					label: `${link.from} to ${link.to}`,
					value: link.line?.total ? money(link.line.total.amount) : '',
					icon: link.icon,
					color: link.color
				}
			]
		};
	}

	// The tooltip is the one of the other report charts (figure-tooltip on layerchart's Tooltip),
	// which keeps itself inside the chart area. The links tell it their data by hand: the chart's
	// own tooltip mode is `manual`.
	let chart = $state.raw<ReturnType<typeof getChartContext> | null>(null);
	const show = (link: SankeyLink, event: PointerEvent) => chart?.tooltip.show(event, link);
	const hide = () => chart?.tooltip.hide();
	// a focused link shows its tooltip at its middle, as a pointer there would
	function showFocused(event: FocusEvent) {
		const el = event.currentTarget as Element;
		const at = el.getBoundingClientRect();
		el.dispatchEvent(
			new PointerEvent('pointermove', {
				bubbles: true,
				clientX: at.left + at.width / 2,
				clientY: at.top + at.height / 2
			})
		);
	}

	const opacityOf = (link: SankeyLink) => (link.kind === 'stayed' ? STAYED_OPACITY : LINK_OPACITY);
	const clip = (label: string) => (label.length > 18 ? `${label.slice(0, 17)}…` : label);
	const ariaOf = (link: SankeyLink) => {
		const tip = describe(link);
		return `${tip.title}: ${tip.rows.map((r) => `${r.label} ${r.value}`).join(', ')}`;
	};
</script>

<!-- Below the minimum width the chart scrolls inside its card instead of overflowing the page. -->
<div class="overflow-x-auto" data-slot="account-sankey">
	<div class="min-w-[640px]">
		<ChartUi.Container config={{}} class="aspect-auto w-full" style={`height: ${height}px`}>
			<Chart
				{data}
				padding={{ left: LABEL_ROOM, right: LABEL_ROOM, top: 4, bottom: 4 }}
				tooltipContext={{ mode: 'manual' }}
			>
				<TipBridge onready={(c) => (chart = c)} />
				<Svg>
					<Sankey
						nodeId={(d: SankeyNode) => d.key}
						nodeWidth={NODE_WIDTH}
						nodePadding={14}
						nodeAlign={(node: { layer: number }) => node.layer}
						nodeSort={(a: { order?: number }, b: { order?: number }) =>
							(a.order ?? 0) - (b.order ?? 0)}
						linkSort={byEnds}
					>
						{#snippet children({ nodes, links })}
							{#each links as raw (raw.key)}
								{@const link = raw as unknown as LaidLink}
								{#if link.kind && link.value > 0}
									{@const fg = dimensionVars(link.color).fg}
									{#snippet band()}
										<Link
											data={link}
											sankey
											orientation="horizontal"
											stroke={fg}
											strokeWidth={link.width}
											fill="none"
											style={`stroke-opacity: ${opacityOf(link)}`}
										/>
									{/snippet}
									<g
										data-link={link.key}
										data-kind={link.kind}
										role="presentation"
										onpointermove={(e) => show(link, e)}
										onpointerleave={hide}
									>
										{#if link.href}
											<a
												href={link.href}
												aria-label={ariaOf(link)}
												class="outline-none focus-visible:[&_path]:stroke-[var(--ring)]"
												onfocus={showFocused}
												onblur={hide}
											>
												{@render band()}
											</a>
										{:else}
											{@render band()}
										{/if}
									</g>
								{/if}
							{/each}
							{#each nodes as raw (raw.key)}
								{@const node = raw as unknown as Laid}
								{@const fg = dimensionVars(node.color).fg}
								{@const Icon = iconFor(node.icon)}
								{@const high = node.y1 - node.y0}
								<g data-node={node.key} data-column={node.column}>
									{#if node.account}
										<rect
											x={node.x0}
											y={node.y0}
											width={node.x1 - node.x0}
											height={high}
											rx="3"
											fill={fg}
										/>
										{#if high >= 20}
											<g transform={`translate(${node.x0 + 3} ${node.y0 + (high - 14) / 2})`}>
												<Icon size={14} class="text-white" aria-hidden="true" />
											</g>
										{/if}
									{:else}
										<rect
											x={node.column === 0 ? node.x1 - BAR_WIDTH : node.x0}
											y={node.y0}
											width={BAR_WIDTH}
											height={high}
											rx="2"
											fill={fg}
										/>
									{/if}
									<text
										x={node.column <= 1
											? (node.column === 0 ? node.x1 - BAR_WIDTH : node.x0) - 6
											: (node.column === 3 ? node.x0 + BAR_WIDTH : node.x1) + 6}
										y={node.y0 + high / 2}
										dy="0.32em"
										text-anchor={node.column <= 1 ? 'end' : 'start'}
										class="fill-foreground text-xs"
										style="paint-order: stroke; stroke: var(--background); stroke-width: 3px; stroke-linejoin: round"
									>
										{clip(node.label)}
									</text>
								</g>
							{/each}
						{/snippet}
					</Sankey>
				</Svg>
				<FigureTooltip {describe} />
			</Chart>
		</ChartUi.Container>
	</div>
</div>
