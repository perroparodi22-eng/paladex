CREATE TABLE `affiliate_clicks` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`offer_id` integer NOT NULL,
	`product_id` integer NOT NULL,
	`retailer_id` integer NOT NULL,
	`source_path` text,
	`was_placeholder` integer DEFAULT false NOT NULL,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `affiliate_clicks_created_idx` ON `affiliate_clicks` (`created_at`);--> statement-breakpoint
CREATE INDEX `affiliate_clicks_product_idx` ON `affiliate_clicks` (`product_id`);--> statement-breakpoint
CREATE TABLE `analytics_events` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`name` text NOT NULL,
	`props` text DEFAULT '{}' NOT NULL,
	`path` text,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `analytics_events_name_idx` ON `analytics_events` (`name`,`created_at`);--> statement-breakpoint
CREATE TABLE `brands` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`country` text,
	`description` text DEFAULT '' NOT NULL,
	`website_url` text,
	`logo_url` text,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `brands_slug_unique` ON `brands` (`slug`);--> statement-breakpoint
CREATE TABLE `editorial_reviews` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`title` text NOT NULL,
	`summary` text NOT NULL,
	`body` text NOT NULL,
	`pros` text DEFAULT '[]' NOT NULL,
	`cons` text DEFAULT '[]' NOT NULL,
	`verdict` text NOT NULL,
	`inspection_notes` text,
	`model_quality_note` text,
	`author` text DEFAULT 'Paladex editorial' NOT NULL,
	`is_sample` integer DEFAULT true NOT NULL,
	`published_at` integer,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `editorial_reviews_product_id_unique` ON `editorial_reviews` (`product_id`);--> statement-breakpoint
CREATE TABLE `model_annotations` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`view` text NOT NULL,
	`title` text NOT NULL,
	`body` text NOT NULL,
	`basis` text DEFAULT 'platform' NOT NULL,
	`sort_order` integer DEFAULT 0 NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `model_assets` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`role` text DEFAULT 'primary' NOT NULL,
	`variant_kind` text DEFAULT 'standard' NOT NULL,
	`label` text DEFAULT 'Standard' NOT NULL,
	`status` text NOT NULL,
	`format` text DEFAULT 'glb' NOT NULL,
	`url` text,
	`preview_url` text,
	`exploded_url` text,
	`version` text DEFAULT '1' NOT NULL,
	`poster_url` text,
	`thumbnail_url` text,
	`supports_explode` integer DEFAULT false NOT NULL,
	`file_size_bytes` integer,
	`triangle_count` integer,
	`bbox` text,
	`material_config` text,
	`notes` text,
	`source` text,
	`license_status` text DEFAULT 'pending' NOT NULL,
	`attribution` text,
	`creator` text,
	`usage_restrictions` text,
	`approval_status` text DEFAULT 'pending' NOT NULL,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `model_assets_product_idx` ON `model_assets` (`product_id`);--> statement-breakpoint
CREATE TABLE `model_hotspots` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`key` text NOT NULL,
	`label` text NOT NULL,
	`body` text NOT NULL,
	`u` real NOT NULL,
	`v` real NOT NULL,
	`w` real NOT NULL,
	`view` text DEFAULT 'front' NOT NULL,
	`spec_key` text,
	`basis` text DEFAULT 'illustrative' NOT NULL,
	`sort_order` integer DEFAULT 0 NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `model_hotspots_product_idx` ON `model_hotspots` (`product_id`);--> statement-breakpoint
CREATE TABLE `model_overlays` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`kind` text NOT NULL,
	`enabled` integer DEFAULT true NOT NULL,
	`basis` text DEFAULT 'illustrative' NOT NULL,
	`note` text,
	`params` text DEFAULT '{}' NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `model_overlays_product_kind` ON `model_overlays` (`product_id`,`kind`);--> statement-breakpoint
CREATE TABLE `offers` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`retailer_id` integer NOT NULL,
	`product_url` text,
	`affiliate_url` text,
	`price_cents` integer NOT NULL,
	`currency` text DEFAULT 'EUR' NOT NULL,
	`stock_status` text DEFAULT 'unknown' NOT NULL,
	`available` integer DEFAULT true NOT NULL,
	`country` text DEFAULT 'EU' NOT NULL,
	`shipping_info` text,
	`last_checked_at` integer,
	`is_demo` integer DEFAULT false NOT NULL,
	`active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`retailer_id`) REFERENCES `retailers`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `offers_product_idx` ON `offers` (`product_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `offers_product_retailer` ON `offers` (`product_id`,`retailer_id`);--> statement-breakpoint
CREATE TABLE `platform_evaluations` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`power` real NOT NULL,
	`control` real NOT NULL,
	`maneuverability` real NOT NULL,
	`forgiveness` real NOT NULL,
	`sweet_spot` real NOT NULL,
	`defense` real NOT NULL,
	`attack` real NOT NULL,
	`best_for` text DEFAULT '' NOT NULL,
	`recommended_for` text DEFAULT '' NOT NULL,
	`not_ideal_for` text DEFAULT '' NOT NULL,
	`methodology_version` text NOT NULL,
	`is_sample` integer DEFAULT true NOT NULL,
	`evaluated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `platform_evaluations_product_id_unique` ON `platform_evaluations` (`product_id`);--> statement-breakpoint
CREATE TABLE `playing_styles` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`description` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `playing_styles_slug_unique` ON `playing_styles` (`slug`);--> statement-breakpoint
CREATE TABLE `product_categories` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`description` text DEFAULT '' NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `product_categories_slug_unique` ON `product_categories` (`slug`);--> statement-breakpoint
CREATE TABLE `product_images` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`url` text NOT NULL,
	`alt` text NOT NULL,
	`kind` text DEFAULT 'front' NOT NULL,
	`sort_order` integer DEFAULT 0 NOT NULL,
	`source` text,
	`license_status` text DEFAULT 'pending' NOT NULL,
	`attribution` text,
	`creator` text,
	`usage_restrictions` text,
	`approval_status` text DEFAULT 'pending' NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `product_playing_styles` (
	`product_id` integer NOT NULL,
	`style_id` integer NOT NULL,
	PRIMARY KEY(`product_id`, `style_id`),
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`style_id`) REFERENCES `playing_styles`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `products` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`category_id` integer NOT NULL,
	`brand_id` integer NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`collection` text,
	`year` integer,
	`short_description` text DEFAULT '' NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`status` text DEFAULT 'draft' NOT NULL,
	`featured` integer DEFAULT false NOT NULL,
	`is_new` integer DEFAULT false NOT NULL,
	`data_status` text DEFAULT 'unverified' NOT NULL,
	`levels` text DEFAULT '[]' NOT NULL,
	`visual` text NOT NULL,
	`indicative_price_cents` integer,
	`currency` text DEFAULT 'EUR' NOT NULL,
	`published_at` integer,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	FOREIGN KEY (`category_id`) REFERENCES `product_categories`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`brand_id`) REFERENCES `brands`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `products_slug_unique` ON `products` (`slug`);--> statement-breakpoint
CREATE INDEX `products_brand_idx` ON `products` (`brand_id`);--> statement-breakpoint
CREATE INDEX `products_status_idx` ON `products` (`status`);--> statement-breakpoint
CREATE TABLE `racket_specs` (
	`product_id` integer PRIMARY KEY NOT NULL,
	`shape` text NOT NULL,
	`weight_min_g` integer,
	`weight_max_g` integer,
	`balance` text,
	`balance_mm` integer,
	`hardness` text,
	`thickness_mm` real,
	`frame_material` text,
	`face_material` text,
	`core_material` text,
	`surface_finish` text,
	`verification` text DEFAULT 'unverified' NOT NULL,
	`source_note` text,
	`source_url` text,
	`verified_at` integer,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `retailers` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`website_url` text NOT NULL,
	`logo_url` text,
	`country` text DEFAULT 'EU' NOT NULL,
	`currency` text DEFAULT 'EUR' NOT NULL,
	`shipping_info` text,
	`affiliate_network` text,
	`allowed_domains` text DEFAULT '[]' NOT NULL,
	`is_demo` integer DEFAULT false NOT NULL,
	`active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch() * 1000) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `retailers_slug_unique` ON `retailers` (`slug`);--> statement-breakpoint
CREATE TABLE `user_reviews` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`product_id` integer NOT NULL,
	`rating` integer NOT NULL,
	`title` text,
	`body` text,
	`display_name` text,
	`status` text DEFAULT 'pending' NOT NULL,
	`created_at` integer DEFAULT (unixepoch() * 1000) NOT NULL,
	FOREIGN KEY (`product_id`) REFERENCES `products`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `user_reviews_product_idx` ON `user_reviews` (`product_id`);