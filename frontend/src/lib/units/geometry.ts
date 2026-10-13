// Where the work panel sits and how large it is: ONE place, decided on the prototype (patterns
// §11.1: a large overlay, roughly half to four fifths of the viewport). It is a slide-in from the
// right with the list dimmed behind it. These classes override the centred geometry of the
// dialog kit's content; change them here to try another shape (centred, wider, full height).
export const PANEL_GEOMETRY = [
	'fixed inset-y-0 right-0 top-0 left-auto h-dvh',
	'w-[min(80vw,1100px)] max-w-none sm:max-w-none',
	'translate-x-0 translate-y-0 rounded-none rounded-l-xl',
	'data-open:slide-in-from-right-8 data-closed:slide-out-to-right-8'
].join(' ');
