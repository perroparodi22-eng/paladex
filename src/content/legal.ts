/**
 * Legal and trust pages. DRAFTS: written to describe what the site actually
 * does today, and to be reviewed by a qualified professional before launch.
 * They make no claim of legal compliance.
 */
import { siteConfig } from "@/config/site";

export interface LegalPage {
  slug: string;
  title: string;
  description: string;
  updated: string;
  sections: Array<{ heading: string; paragraphs: string[]; list?: string[] }>;
}

const name = siteConfig.name;

export const LEGAL_PAGES: LegalPage[] = [
  {
    slug: "affiliate-disclosure",
    title: "Affiliate disclosure",
    description: `How ${name} earns money and why that doesn't change our evaluations.`,
    updated: "2026-10-05",
    sections: [
      {
        heading: "How we make money",
        paragraphs: [
          `${name} may earn a commission when you buy through certain links on this site. This does not affect the price you pay and does not influence our independent evaluations.`,
          "Retailer links go through a redirect on our domain (/go/…), which lets us count clicks anonymously before sending you to the shop. We don't store your IP address, your browser details, or any cookie for this.",
        ],
      },
      {
        heading: "What commissions never change",
        paragraphs: [
          "Platform scores, the Racket Finder and the order of results are calculated the same way whether or not a retailer pays us. Scores are our evaluations, labelled as such, and are never presented as manufacturer measurements.",
        ],
      },
      {
        heading: "Current status",
        paragraphs: [
          "While the site is in development, retailers and prices are sample data and affiliate links are placeholders. Buttons that lead to a placeholder link take you to a page that says so, and they never pretend to complete a purchase.",
        ],
      },
    ],
  },
  {
    slug: "3d-assets",
    title: "3D asset and model disclaimer",
    description: "Where our 3D models come from, what each label means, and what the visualisations do and don't show.",
    updated: "2026-10-05",
    sections: [
      {
        heading: "Every model is labelled",
        paragraphs: ["Each 3D viewer shows a badge stating where its model comes from:"],
        list: [
          "Official manufacturer model: supplied by the brand.",
          "Licensed model: licensed from a third party.",
          `Platform-created model: built by ${name} to represent the real racket, for example from reference photos. It is not supplied or endorsed by the manufacturer, and fine details (thickness profile, internal construction, exact textures) are approximations.`,
          "Placeholder model: a generic racket of the right shape class in our own colours. It is not the real design and will be replaced.",
          "No 3D model yet: an image or illustration is shown instead.",
        ],
      },
      {
        heading: "Visualisations are explanations, not measurements",
        paragraphs: [
          "Overlays such as the sweet spot, impact zone and weight distribution illustrate concepts for a shape class. The balance point uses the manufacturer's published value when we have one, and is otherwise estimated from the published balance category and labelled as estimated. The exploded 'material layers' view shows a generic layer order, not a racket's verified construction.",
        ],
      },
      {
        heading: "Trademarks and imagery",
        paragraphs: [
          "Brand names, logos and product designs belong to their owners and are shown to identify the products being described. Product photos are used with the provenance recorded in our asset records. If you own an asset and want it changed or removed, contact us.",
        ],
      },
    ],
  },
  {
    slug: "privacy",
    title: "Privacy policy",
    description: `What data ${name} processes and why. Draft for professional review.`,
    updated: "2026-10-05",
    sections: [
      {
        heading: "Summary",
        paragraphs: [
          "You can browse the whole site without an account. We don't use advertising trackers and don't sell data.",
        ],
      },
      {
        heading: "What we process",
        paragraphs: ["Depending on configuration, the site may record:"],
        list: [
          "Anonymous usage events (for example 'racket viewed' or '3D viewer opened') with the page path and a few non-identifying details. There are no cookies, no IP addresses and no user identifiers. Browsers that send a Global Privacy Control signal are not tracked.",
          "Anonymous clicks on retailer links, counted per offer and page.",
          "Your comparison picks and viewer settings, stored only in your own browser (local storage). They never leave your device.",
          "Server logs kept by our hosting provider for security and reliability.",
        ],
      },
      {
        heading: "Your rights",
        paragraphs: [
          "Depending on where you live (for example under the EU GDPR) you may have rights of access, correction, deletion and objection. Contact us using the details on the Contact page. [To complete: data controller identity, legal bases, retention periods, processors and international transfers.]",
        ],
      },
    ],
  },
  {
    slug: "cookies",
    title: "Cookie policy",
    description: "Which cookies and similar technologies the site uses.",
    updated: "2026-10-05",
    sections: [
      {
        heading: "Visitors",
        paragraphs: [
          "The public site sets no cookies. Preferences such as your comparison list and 3D quality setting are kept in your browser's local storage. They are never sent to us, and you can clear them at any time in your browser settings.",
        ],
      },
      {
        heading: "Administrators",
        paragraphs: ["The admin area uses one strictly necessary, HttpOnly session cookie to keep administrators signed in."],
      },
      {
        heading: "Retailers",
        paragraphs: [
          "When you follow a link to a retailer, that shop (and its affiliate network) may set its own cookies on its own site, under its own policy.",
        ],
      },
    ],
  },
  {
    slug: "terms",
    title: "Terms of use",
    description: "The basic terms for using the site. Draft for professional review.",
    updated: "2026-10-05",
    sections: [
      {
        heading: "Information, not advice",
        paragraphs: [
          "Specifications are compiled from public sources and may be incomplete or out of date. They are marked when not yet verified. Scores and recommendations are our opinion. Check the details with the manufacturer or retailer before you buy.",
        ],
      },
      {
        heading: "Prices and availability",
        paragraphs: [
          "Prices and stock are provided by retailers or entered manually and can change at any time. Purchases are made with the retailer, under the retailer's terms. We are not a party to the sale.",
        ],
      },
      {
        heading: "Content",
        paragraphs: ["Site content, 3D models we create and the design of the site are protected. Please don't copy them wholesale. [To complete: governing law, liability limits, operator details.]"],
      },
    ],
  },
];

export function getLegalPage(slug: string) {
  return LEGAL_PAGES.find((p) => p.slug === slug);
}
