import { QueryClient } from '@tanstack/vue-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
})

export async function resetQueriesForActorContextChange(): Promise<void> {
  await queryClient.resetQueries()
}
