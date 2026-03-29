# Design System Specification: The Cognitive Atelier

## 1. Overview & Creative North Star: "The Digital Curator"
This design system moves beyond the utility of a standard tool to become a "Digital Curator." While many AI interfaces feel like sterile terminals, this system aims for an **Editorial High-Performance** aesthetic. It blends the structural clarity of a premium workspace with the kinetic, high-density speed of a professional developer tool.

**The Creative North Star:** We are building a "Gallery of Thought." The interface should feel like a physical desk made of dark, polished obsidian—where information isn't just "displayed," but curated. We break the "template" look through intentional asymmetry: heavy-weighted headers, generous breathing room (white space) in content areas, and high-contrast typography scales that guide the eye with authoritative precision.

---

## 2. Colors & Tonal Depth
Our palette is rooted in deep, ink-like foundations to allow our signature AI Indigos and semantic accents to glow with intentionality.

### The Foundation (Dark Mode Only)
*   **Background:** `#0b1326` (The base "Canvas")
*   **Surface:** `#0b1326`
*   **Surface Container Low:** `#131b2e` (Secondary sections)
*   **Surface Container High:** `#222a3d` (Primary interaction cards)

### Brand & Accents
*   **Primary (AI Core):** `Indigo (#4F46E5)` / Token: `primary_container`
*   **Projects:** `Emerald (#10B981)` / Token: `secondary`
*   **Events:** `Amber (#F59E0B)` / Token: `on_tertiary_fixed_variant`
*   **People:** `Teal (#14B8A6)` / Token: `secondary_fixed`
*   **Ideas:** `Rose (#F43F5E)` / Token: `tertiary_container`

### Rules of Engagement
*   **The "No-Line" Rule:** 1px solid borders are strictly prohibited for sectioning. Define boundaries solely through background color shifts. A `surface-container-low` section sitting on a `surface` background provides all the separation a premium UI needs.
*   **The "Glass & Gradient" Rule:** Floating elements (Modals, Popovers, Command Bars) must use Glassmorphism. Apply `surface_bright` at 60% opacity with a `backdrop-blur: 20px`. 
*   **Signature Textures:** Use a subtle linear gradient on primary CTAs: `primary_container` (#4F46E5) to `primary` (#c3c0ff) at a 135-degree angle. This adds "soul" to the button that flat HEX codes cannot achieve.

---

## 3. Typography: Editorial Authority
We utilize the Inter/SF Pro stack to maintain a system-native feel, but we manipulate the scale to create an editorial hierarchy.

*   **Display (Display-LG: 3.5rem):** Used for empty states and major dashboard welcomes. Track tightly (-0.02em).
*   **Headline (Headline-MD: 1.75rem):** The primary anchor for knowledge nodes. High contrast against body text.
*   **Body (Body-MD: 0.875rem):** The "Workhorse." Line height must be set to 1.6 for maximum readability in AI-generated markdown.
*   **Label (Label-SM: 0.6875rem):** All-caps with 0.05em letter spacing for metadata (e.g., "LAST EDITED BY...").

---

## 4. Elevation & Depth: Tonal Layering
In this system, depth is a product of light and material, not lines.

*   **The Layering Principle:** Stack surfaces to create focus. 
    *   *Level 0:* `surface` (The App Background)
    *   *Level 1:* `surface-container-low` (Sidebar/Navigation)
    *   *Level 2:* `surface-container-highest` (Content Cards)
*   **Ambient Shadows:** For floating elements, use a "Tinted Glow" instead of a gray shadow. 
    *   *Spec:* `0 20px 40px rgba(0, 0, 0, 0.4), 0 0 8px rgba(79, 70, 229, 0.1)` (A hint of Indigo in the shadow).
*   **The Ghost Border Fallback:** If a container sits on a background of the same color, use a "Ghost Border": `outline_variant` at **15% opacity**. It should be felt, not seen.

---

## 5. Signature Components

### Markdown Chat Bubbles
*   **User Prompt:** `surface_container_high` with a 0.75rem (xl) radius. Right-aligned.
*   **AI Response:** No background. Content sits directly on the `surface`. Use a 4px `primary` left-border (accent) to indicate the "active" thought stream. 
*   **Code Blocks:** `surface_container_lowest` with a 0.35rem (1) padding.

### Cards & Knowledge Nodes
*   **Constraint:** No dividers. Use **Spacing 6 (2rem)** to separate content chunks.
*   **Visual Shift:** On hover, a card should shift from `surface_container_highest` to `surface_bright`. 

### Refined Sidebar
*   **Width:** 240px. 
*   **Background:** `surface_container_low`.
*   **Active State:** No "pill" background. Use a `primary` vertical line (2px wide) on the far left of the item and shift the text color to `on_surface`.

### Control Toggles
*   **Unselected:** `outline_variant`.
*   **Selected:** `primary_container` with a subtle `primary` inner glow.

---

## 6. Do’s and Don’ts

### Do
*   **Do** use asymmetrical margins. Give the right side of the layout more room than the left to mimic a premium magazine layout.
*   **Do** use `secondary` (Emerald) and `tertiary` (Rose) as tiny "jewel" accents (dots/icons) rather than large background blocks.
*   **Do** embrace verticality. Use the Spacing Scale (12, 16, 20) to let major sections breathe.

### Don't
*   **Don't** use pure white (#FFFFFF) for text. Always use `on_surface` or `on_surface_variant` to prevent eye strain against the deep background.
*   **Don't** use standard "Drop Shadows." If it doesn't look like it’s glowing or floating in a physical space, the shadow is too heavy.
*   **Don't** use 1px borders to separate list items. Use the `surface-container` hierarchy or whitespace.