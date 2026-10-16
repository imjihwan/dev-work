CREATE TABLE `history` (
	`id` text PRIMARY KEY NOT NULL,
	`recipe_id` text,
	`action` text NOT NULL,
	`actor` text NOT NULL,
	`created` text NOT NULL,
	`before` text,
	`after` text
);
--> statement-breakpoint
CREATE TABLE `locks` (
	`id` text PRIMARY KEY NOT NULL,
	`token` text NOT NULL,
	`expires` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `members` (
	`email` text PRIMARY KEY NOT NULL,
	`user_id` text,
	`role` text NOT NULL,
	`name` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `recipes` (
	`id` text PRIMARY KEY NOT NULL,
	`remote_id` text,
	`name` text NOT NULL,
	`data` text NOT NULL,
	`base` text,
	`revision` integer DEFAULT 1 NOT NULL,
	`state` text NOT NULL,
	`scope` text NOT NULL,
	`updated` text NOT NULL,
	`actor` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `workspace` (
	`id` text PRIMARY KEY NOT NULL,
	`owner` text NOT NULL,
	`account` text,
	`connected` integer DEFAULT 0 NOT NULL,
	`last_sync` text,
	`device` text,
	`slots` text,
	`error` text
);
