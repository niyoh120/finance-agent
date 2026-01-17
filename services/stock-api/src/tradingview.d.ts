declare module '@mathieuc/tradingview' {
    export class Client {
        Session: {
            Quote: new (options?: { fields?: string }) => QuoteSession;
            Chart: new (options?: any) => any;
        }
        end(): void;
    }

    interface QuoteSession {
        Market: new (symbol: string) => Market;
    }

    interface Market {
        onData(callback: (data: any) => void): void;
        onError(callback: (err: any) => void): void;
    }
}
