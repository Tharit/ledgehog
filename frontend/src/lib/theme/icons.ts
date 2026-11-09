// A curated, explicit map from icon NAME to Lucide component (design.md §6). Names are what the
// API stores; a name that is not here renders as the default. One import per icon keeps the bundle
// to the icons the design offers (no dynamic import of the whole library).

import type { Component } from 'svelte';

import ArrowLeftRightIcon from '@lucide/svelte/icons/arrow-left-right';
import BabyIcon from '@lucide/svelte/icons/baby';
import BanknoteIcon from '@lucide/svelte/icons/banknote';
import BikeIcon from '@lucide/svelte/icons/bike';
import BookOpenIcon from '@lucide/svelte/icons/book-open';
import BriefcaseIcon from '@lucide/svelte/icons/briefcase';
import Building2Icon from '@lucide/svelte/icons/building-2';
import BusIcon from '@lucide/svelte/icons/bus';
import CarIcon from '@lucide/svelte/icons/car';
import ChartLineIcon from '@lucide/svelte/icons/chart-line';
import CheckIcon from '@lucide/svelte/icons/check';
import CircleDashedIcon from '@lucide/svelte/icons/circle-dashed';
import CircleEllipsisIcon from '@lucide/svelte/icons/circle-ellipsis';
import CircleParkingIcon from '@lucide/svelte/icons/circle-parking';
import CircleQuestionMarkIcon from '@lucide/svelte/icons/circle-question-mark';
import ClockIcon from '@lucide/svelte/icons/clock';
import CoffeeIcon from '@lucide/svelte/icons/coffee';
import CoinsIcon from '@lucide/svelte/icons/coins';
import CreditCardIcon from '@lucide/svelte/icons/credit-card';
import DropletIcon from '@lucide/svelte/icons/droplet';
import DumbbellIcon from '@lucide/svelte/icons/dumbbell';
import FileTextIcon from '@lucide/svelte/icons/file-text';
import FilmIcon from '@lucide/svelte/icons/film';
import FlagIcon from '@lucide/svelte/icons/flag';
import FlameIcon from '@lucide/svelte/icons/flame';
import FuelIcon from '@lucide/svelte/icons/fuel';
import Gamepad2Icon from '@lucide/svelte/icons/gamepad-2';
import GaugeIcon from '@lucide/svelte/icons/gauge';
import GemIcon from '@lucide/svelte/icons/gem';
import GiftIcon from '@lucide/svelte/icons/gift';
import GraduationCapIcon from '@lucide/svelte/icons/graduation-cap';
import HammerIcon from '@lucide/svelte/icons/hammer';
import HandCoinsIcon from '@lucide/svelte/icons/hand-coins';
import HeartPulseIcon from '@lucide/svelte/icons/heart-pulse';
import HourglassIcon from '@lucide/svelte/icons/hourglass';
import HouseIcon from '@lucide/svelte/icons/house';
import InboxIcon from '@lucide/svelte/icons/inbox';
import LampIcon from '@lucide/svelte/icons/lamp';
import LandmarkIcon from '@lucide/svelte/icons/landmark';
import LeafIcon from '@lucide/svelte/icons/leaf';
import MusicIcon from '@lucide/svelte/icons/music';
import PackageIcon from '@lucide/svelte/icons/package';
import PartyPopperIcon from '@lucide/svelte/icons/party-popper';
import PawPrintIcon from '@lucide/svelte/icons/paw-print';
import PercentIcon from '@lucide/svelte/icons/percent';
import PiggyBankIcon from '@lucide/svelte/icons/piggy-bank';
import PillIcon from '@lucide/svelte/icons/pill';
import PizzaIcon from '@lucide/svelte/icons/pizza';
import PlaneIcon from '@lucide/svelte/icons/plane';
import ReceiptIcon from '@lucide/svelte/icons/receipt';
import RepeatIcon from '@lucide/svelte/icons/repeat';
import ScaleIcon from '@lucide/svelte/icons/scale';
import ScissorsIcon from '@lucide/svelte/icons/scissors';
import ShapesIcon from '@lucide/svelte/icons/shapes';
import ShieldIcon from '@lucide/svelte/icons/shield';
import ShirtIcon from '@lucide/svelte/icons/shirt';
import ShoppingBasketIcon from '@lucide/svelte/icons/shopping-basket';
import ShoppingCartIcon from '@lucide/svelte/icons/shopping-cart';
import SigmaIcon from '@lucide/svelte/icons/sigma';
import SmartphoneIcon from '@lucide/svelte/icons/smartphone';
import SparklesIcon from '@lucide/svelte/icons/sparkles';
import StethoscopeIcon from '@lucide/svelte/icons/stethoscope';
import StoreIcon from '@lucide/svelte/icons/store';
import TentIcon from '@lucide/svelte/icons/tent';
import TicketIcon from '@lucide/svelte/icons/ticket';
import TrainFrontIcon from '@lucide/svelte/icons/train-front';
import TreePalmIcon from '@lucide/svelte/icons/tree-palm';
import TrendingUpIcon from '@lucide/svelte/icons/trending-up';
import TruckIcon from '@lucide/svelte/icons/truck';
import TvIcon from '@lucide/svelte/icons/tv';
import UnlinkIcon from '@lucide/svelte/icons/unlink';
import UserIcon from '@lucide/svelte/icons/user';
import UsersIcon from '@lucide/svelte/icons/users';
import UtensilsIcon from '@lucide/svelte/icons/utensils';
import VaultIcon from '@lucide/svelte/icons/vault';
import WalletIcon from '@lucide/svelte/icons/wallet';
import WalletCardsIcon from '@lucide/svelte/icons/wallet-cards';
import WifiIcon from '@lucide/svelte/icons/wifi';
import WineIcon from '@lucide/svelte/icons/wine';
import WrenchIcon from '@lucide/svelte/icons/wrench';
import ZapIcon from '@lucide/svelte/icons/zap';

export type IconComponent = Component<{
	size?: number;
	strokeWidth?: number;
	class?: string;
	'aria-hidden'?: 'true';
}>;

export const DEFAULT_ICON = 'shapes';

const ICONS: Record<string, IconComponent> = {
	'arrow-left-right': ArrowLeftRightIcon,
	baby: BabyIcon,
	banknote: BanknoteIcon,
	bike: BikeIcon,
	'book-open': BookOpenIcon,
	briefcase: BriefcaseIcon,
	'building-2': Building2Icon,
	bus: BusIcon,
	car: CarIcon,
	'chart-line': ChartLineIcon,
	check: CheckIcon,
	'circle-dashed': CircleDashedIcon,
	'circle-ellipsis': CircleEllipsisIcon,
	'circle-parking': CircleParkingIcon,
	'circle-question-mark': CircleQuestionMarkIcon,
	clock: ClockIcon,
	coffee: CoffeeIcon,
	coins: CoinsIcon,
	'credit-card': CreditCardIcon,
	droplet: DropletIcon,
	dumbbell: DumbbellIcon,
	'file-text': FileTextIcon,
	film: FilmIcon,
	flag: FlagIcon,
	flame: FlameIcon,
	fuel: FuelIcon,
	'gamepad-2': Gamepad2Icon,
	gauge: GaugeIcon,
	gem: GemIcon,
	gift: GiftIcon,
	'graduation-cap': GraduationCapIcon,
	hammer: HammerIcon,
	'hand-coins': HandCoinsIcon,
	'heart-pulse': HeartPulseIcon,
	hourglass: HourglassIcon,
	house: HouseIcon,
	inbox: InboxIcon,
	lamp: LampIcon,
	landmark: LandmarkIcon,
	leaf: LeafIcon,
	music: MusicIcon,
	package: PackageIcon,
	'party-popper': PartyPopperIcon,
	'paw-print': PawPrintIcon,
	percent: PercentIcon,
	'piggy-bank': PiggyBankIcon,
	pill: PillIcon,
	pizza: PizzaIcon,
	plane: PlaneIcon,
	receipt: ReceiptIcon,
	repeat: RepeatIcon,
	scale: ScaleIcon,
	scissors: ScissorsIcon,
	shapes: ShapesIcon,
	shield: ShieldIcon,
	shirt: ShirtIcon,
	'shopping-basket': ShoppingBasketIcon,
	'shopping-cart': ShoppingCartIcon,
	sigma: SigmaIcon,
	smartphone: SmartphoneIcon,
	sparkles: SparklesIcon,
	stethoscope: StethoscopeIcon,
	store: StoreIcon,
	tent: TentIcon,
	ticket: TicketIcon,
	'train-front': TrainFrontIcon,
	'tree-palm': TreePalmIcon,
	'trending-up': TrendingUpIcon,
	truck: TruckIcon,
	tv: TvIcon,
	unlink: UnlinkIcon,
	user: UserIcon,
	users: UsersIcon,
	utensils: UtensilsIcon,
	vault: VaultIcon,
	wallet: WalletIcon,
	'wallet-cards': WalletCardsIcon,
	wifi: WifiIcon,
	wine: WineIcon,
	wrench: WrenchIcon,
	zap: ZapIcon
};

/** Is this a name of the curated set? */
export function isKnownIcon(name: string | null | undefined): name is string {
	return typeof name === 'string' && Object.hasOwn(ICONS, name);
}

/** The component for an icon name; an unknown or missing name gives the default. */
export function iconFor(name: string | null | undefined): IconComponent {
	return isKnownIcon(name) ? ICONS[name] : ICONS[DEFAULT_ICON];
}
