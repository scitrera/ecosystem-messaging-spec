/**
 * @scitrera/messaging-spec — TypeScript reference implementation.
 *
 * See ../docs/UNIVERSAL_MESSAGE_SPEC.md for the normative spec.
 */
export * from './schema';
export * from './tools';
export * from './events';
export * from './memorylayer';
export {applyEvent, reduceEvents, type MessageState} from './applyEvent';
