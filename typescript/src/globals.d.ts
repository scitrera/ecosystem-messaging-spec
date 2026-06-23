/**
 * Ambient declarations for globals that aren't in ES2022 lib but are
 * standard in every runtime this package supports (Node 17+, modern
 * browsers via HTML Living Standard).
 *
 * Declaring them here keeps the package free of a DOM/Node lib choice
 * — consumers' tsconfigs control their own lib set.
 */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
declare function structuredClone<T>(value: T, options?: {transfer?: unknown[]}): T;
