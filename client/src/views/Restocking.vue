<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
        </div>
        <div class="budget-slider">
          <input
            type="range"
            min="0"
            max="100000"
            step="1000"
            v-model.number="budget"
          />
          <div class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</div>
        </div>
        <p class="budget-hint">{{ t('restocking.budgetHint') }}</p>
      </div>

      <div v-if="orderSuccessMessage" class="success-banner">{{ orderSuccessMessage }}</div>
      <div v-if="orderErrorMessage" class="error">{{ orderErrorMessage }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
        </div>
        <div v-if="rows.length === 0" class="no-items">{{ t('restocking.noEligibleItems') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.currentDemand') }}</th>
                <th>{{ t('restocking.table.forecastedDemand') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.include') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.sku">
                <td><strong>{{ row.sku }}</strong></td>
                <td>{{ row.name }}</td>
                <td>{{ row.currentDemand }}</td>
                <td>{{ row.forecastedDemand }}</td>
                <td>{{ row.shortfallQty }}</td>
                <td>{{ formatCurrency(row.unitCost, currentCurrency) }}</td>
                <td>
                  <input type="number" min="0" v-model.number="row.quantity" class="quantity-input" />
                </td>
                <td>
                  <input type="checkbox" v-model="row.selected" />
                </td>
                <td><strong>{{ formatCurrency(row.quantity * row.unitCost, currentCurrency) }}</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card summary-bar">
        <div class="summary-row">
          <span class="summary-label">{{ t('restocking.runningTotal') }}</span>
          <span class="summary-value">{{ formatCurrency(runningTotal, currentCurrency) }}</span>
        </div>
        <div class="summary-row">
          <span class="summary-label">{{ t('restocking.budgetRemaining') }}</span>
          <span class="summary-value" :class="{ 'over-budget': budgetRemaining < 0 }">
            {{ formatCurrency(budgetRemaining, currentCurrency) }}
          </span>
        </div>
        <p v-if="runningTotal === 0" class="summary-warning">{{ t('restocking.noItemsSelected') }}</p>
        <p v-else-if="budgetRemaining < 0" class="summary-warning">{{ t('restocking.overBudgetWarning') }}</p>
        <button
          class="place-order-btn"
          :disabled="isPlaceOrderDisabled"
          @click="placeOrder"
        >
          {{ placingOrder ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, watch, computed } from 'vue'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()
    const { selectedLocation, selectedCategory, getCurrentFilters } = useFilters()

    const loading = ref(true)
    const error = ref(null)
    const allForecasts = ref([])
    const inventoryItems = ref([])

    const budget = ref(25000)
    const rows = ref([])

    const placingOrder = ref(false)
    const orderSuccessMessage = ref(null)
    const orderErrorMessage = ref(null)

    const buildRecommendations = () => {
      const inventoryBySku = new Map(inventoryItems.value.map(item => [item.sku, item]))

      const candidates = allForecasts.value
        .map(forecast => {
          const item = inventoryBySku.get(forecast.item_sku)
          if (!item) return null
          if (!(forecast.forecasted_demand > forecast.current_demand)) return null

          const shortfallQty = forecast.forecasted_demand - forecast.current_demand
          const shortfallPct = forecast.current_demand > 0
            ? shortfallQty / forecast.current_demand
            : Infinity
          const recommendedCost = shortfallQty * item.unit_cost

          return {
            sku: forecast.item_sku,
            name: forecast.item_name,
            currentDemand: forecast.current_demand,
            forecastedDemand: forecast.forecasted_demand,
            shortfallQty,
            shortfallPct,
            unitCost: item.unit_cost,
            recommendedCost
          }
        })
        .filter(c => c !== null)

      candidates.sort((a, b) => {
        if (b.shortfallPct !== a.shortfallPct) return b.shortfallPct - a.shortfallPct
        if (b.shortfallQty !== a.shortfallQty) return b.shortfallQty - a.shortfallQty
        return a.sku.localeCompare(b.sku)
      })

      let runningCost = 0
      rows.value = candidates.map(c => {
        let selected = false
        if (runningCost + c.recommendedCost <= budget.value) {
          selected = true
          runningCost += c.recommendedCost
        }
        return {
          sku: c.sku,
          name: c.name,
          currentDemand: c.currentDemand,
          forecastedDemand: c.forecastedDemand,
          shortfallQty: c.shortfallQty,
          unitCost: c.unitCost,
          quantity: c.shortfallQty,
          selected
        }
      })
    }

    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        const filters = getCurrentFilters()

        const [forecastsData, inventoryData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory({
            warehouse: filters.warehouse,
            category: filters.category
          })
        ])

        allForecasts.value = forecastsData
        inventoryItems.value = inventoryData
        buildRecommendations()
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    }

    watch([selectedLocation, selectedCategory], () => {
      loadData()
    })

    watch(budget, () => {
      buildRecommendations()
    })

    const runningTotal = computed(() => {
      return rows.value
        .filter(row => row.selected)
        .reduce((sum, row) => sum + (row.quantity * row.unitCost), 0)
    })

    const budgetRemaining = computed(() => budget.value - runningTotal.value)

    const isPlaceOrderDisabled = computed(() => {
      return placingOrder.value || runningTotal.value === 0 || budgetRemaining.value < 0
    })

    const placeOrder = async () => {
      orderSuccessMessage.value = null
      orderErrorMessage.value = null
      placingOrder.value = true

      try {
        const items = rows.value
          .filter(row => row.selected && row.quantity > 0)
          .map(row => ({
            sku: row.sku,
            name: row.name,
            quantity: row.quantity,
            unit_cost: row.unitCost,
            line_total: row.quantity * row.unitCost
          }))

        const result = await api.createRestockOrder({
          budget: budget.value,
          items
        })

        orderSuccessMessage.value = t('restocking.orderSuccess', {
          orderNumber: result.order_number,
          leadTimeDays: result.lead_time_days,
          expectedDelivery: result.expected_delivery
        })

        buildRecommendations()
      } catch (err) {
        orderErrorMessage.value = t('restocking.orderError')
      } finally {
        placingOrder.value = false
      }
    }

    onMounted(loadData)

    return {
      t,
      currentCurrency,
      loading,
      error,
      budget,
      rows,
      runningTotal,
      budgetRemaining,
      isPlaceOrderDisabled,
      placingOrder,
      orderSuccessMessage,
      orderErrorMessage,
      placeOrder,
      formatCurrency
    }
  }
}
</script>

<style scoped>
.budget-slider {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.budget-slider input[type='range'] {
  flex: 1;
}

.budget-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 100px;
  text-align: right;
}

.budget-hint {
  margin-top: 0.75rem;
  color: #64748b;
  font-size: 0.875rem;
}

.no-items {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

.quantity-input {
  width: 80px;
  padding: 0.25rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.summary-bar {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 1rem;
}

.summary-label {
  color: #64748b;
  font-weight: 600;
}

.summary-value {
  font-weight: 700;
  color: #0f172a;
}

.summary-value.over-budget {
  color: #dc2626;
}

.summary-warning {
  color: #dc2626;
  font-size: 0.875rem;
  font-weight: 500;
}

.place-order-btn {
  align-self: flex-start;
  margin-top: 0.5rem;
  padding: 0.625rem 1.5rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
