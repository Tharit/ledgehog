# Household ledger — UI Design Specification

Status: **draft, written before the first screen, based on mockups.** 

# Design philosophy
Ledgehog is a personal household finance application with a warm, friendly, understated visual identity.
Core principles: Warm, not sterile. Playful, not childish. Spacious, not wasteful. Data-rich, not cluttered.
Use soft cream and beige surfaces instead of white or neutral gray. Forest green anchors the identity, with muted earthy accents for charts and interactions.

# Color palette
The following HEX values are approximate visual matches to the first mockup, rather than exact values extracted from the generated image.
Token	Hex	Usage
background	#F7F0E6	Main application background
sidebar	#F3E9DA	Navigation sidebar
surface	#FFFAF3	Cards, dialogs, panels
surface-muted	#F5EDE2	Inputs, secondary surfaces
border	#E9DED0	Subtle borders and dividers
primary	#24483D	Buttons, links, brand identity
primary-hover	#356554	Hover and interactive states
sage	#91A88D	Selected navigation, chart fills
text	#172923	Primary text, headings, figures
text-muted	#82796E	Labels, descriptions, metadata
terracotta	#C76F50	Expenses, warnings, chart accents
ochre	#D7A25E	Secondary chart categories
positive	#4F956F	Income, positive changes
negative	#C65D45	Expenses, negative changes

Warm neutrals, forest green, sage, and earthy accents.
Avoid pure white (#FFFFFF) and generic cool-gray backgrounds as primary surfaces.

# Typography
Preferred font: Inter, with system sans-serif fallback.
- Page headings: 28–32px, semibold (600–700).
- Section headings: 16–18px, semibold (600).
- Body: 14px, regular (400).
- Labels and metadata: 12–13px, regular/medium.
- Financial KPI values: 26–32px, bold (700).
Use tabular numerals for financial values and align amounts consistently to the right. Avoid decorative fonts and excessive uppercase lettering.

# Layout and whitespace
Use a consistent 8px spacing system, with 4px increments for compact elements.
Element	Specification
Sidebar width	220–240px
Main content padding	24–32px
Card padding	20–24px
Card gaps	14–20px
Card corner radius	12–14px
Button/input radius	8–10px
Active navigation radius	8px
Borders	1px, low contrast
Shadows	Very soft, warm-toned, minimal
Prefer generous whitespace around section headings and between content blocks. Dense tables may use tighter spacing.

# Icons
- Rounded, minimalist line icons, preferably Lucide.
- Stroke width: approximately 1.75–2px.
- Standard size: 18–20px.
- Default color: muted dark brown or green.
- Use subtle pastel backgrounds for transaction-category icons.
- Avoid glossy, 3D, or heavily filled icons.

# Mascot and branding
The mascot is a friendly brown hedgehog with a cream face, small expressive features, and a dark-green ledger book.
Use it selectively:
- Sidebar: Small hedgehog head next to the Ledgehog wordmark.
- Empty states/onboarding: Larger expressive illustrations.
- Favicon: Simplified cream hedgehog silhouette on forest-green background.
Keep the mascot visually consistent, flat/vector-like, and recognizable at small sizes. Avoid placing illustrations in dense data views.

# Components and data visualization
Cards: Warm off-white surfaces with thin borders, subtle shadows, and rounded corners. No heavy gradients or pronounced elevation.
Navigation: Light beige sidebar; selected item has a muted sage/beige background. Avoid bright primary-color selection blocks.
Charts: Thin forest-green lines, translucent sage fills, minimal gridlines. Use muted earthy colors for categorical charts. Avoid saturated rainbow palettes.
Tables: Subtle horizontal separators, no heavy grid. Right-aligned numerical columns. Use clear income/expense indicators and compact category icons.
Buttons: Dark forest-green primary buttons with cream text. Secondary buttons should use soft beige backgrounds or subtle outlines.

# Overall visual rule
The UI should feel like a thoughtfully designed personal finance notebook, not enterprise accounting software or a generic banking dashboard.
Use the first Ledgehog dashboard mockup as the canonical reference for colors, typography, spacing, illustrations, and overall visual tone. Functional layouts may evolve independently, but should preserve this visual language. Note: the layout & structure of content is explicitly illustrative only; do not use it as reference beyond the design, as it might contradict other parts of the spec - the spec is authoritative on layout, patterns, etc.