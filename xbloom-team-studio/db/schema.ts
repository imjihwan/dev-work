// Intentionally empty by default.
// Add Drizzle tables here when the site actually needs a database.
// See examples/d1/db/schema.ts for an opt-in example.
import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const workspace = sqliteTable('workspace', { id: text('id').primaryKey(), owner: text('owner').notNull(), account: text('account'), connected: integer('connected').notNull().default(0), lastSync: text('last_sync'), device: text('device'), slots: text('slots'), error: text('error'), groups: text('groups') });
export const members = sqliteTable('members', { email: text('email').primaryKey(), userId: text('user_id'), role: text('role').notNull(), name: text('name').notNull() });
export const recipes = sqliteTable('recipes', { id: text('id').primaryKey(), remoteId: text('remote_id'), name: text('name').notNull(), data: text('data').notNull(), base: text('base'), revision: integer('revision').notNull().default(1), state: text('state').notNull(), scope: text('scope').notNull(), updated: text('updated').notNull(), actor: text('actor').notNull() });
export const history = sqliteTable('history', { id: text('id').primaryKey(), recipeId: text('recipe_id'), action: text('action').notNull(), actor: text('actor').notNull(), created: text('created').notNull(), before: text('before'), after: text('after') });
export const locks = sqliteTable('locks', { id: text('id').primaryKey(), token: text('token').notNull(), expires: integer('expires').notNull() });
