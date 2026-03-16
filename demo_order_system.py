class OrderValidator:
    """简化的订单验证器"""
    
    def validate_order(self, order_data):
        """验证订单数据"""
        if not order_data:
            return False, "订单数据为空"
        
        # 检查必需字段
        required = ['order_id', 'items', 'customer_id']
        for field in required:
            if field not in order_data:
                return False, f"缺少字段: {field}"
        
        # 简单验证订单ID
        if not order_data['order_id']:
            return False, "订单ID无效"
        
        # 简单验证商品
        if not order_data.get('items'):
            return False, "无商品"
            
        return True, ""


def calculate_total(items):
    """计算订单总金额"""
    if not items:
        return 0.0
    
    total = 0.0
    for item in items:
        price = item.get('price', 0)
        quantity = item.get('quantity', 0)
        total += price * quantity
    
    return round(total, 2)


def apply_discount(total, discount_code=None):
    """应用折扣"""
    if not discount_code:
        return total
    
    # 折扣规则
    discounts = {
        'SAVE10': 0.10,
        'SAVE20': 0.20,
        'VIP30': 0.30,
    }
    
    if discount_code in discounts:
        total *= (1 - discounts[discount_code])
    
    return round(total, 2)


def calculate_shipping(total, province=None, is_vip=False):
    """计算运费"""
    if is_vip or total >= 99:
        return 0.0
    
    # 偏远地区
    if province in ['西藏', '新疆', '青海']:
        return 20.0
    
    return 10.0


def process_order(order_data):
    """处理订单主函数"""
    result = {
        'success': False,
        'error': None,
        'total': 0.0,
        'shipping': 0.0,
        'final': 0.0
    }
    
    try:
        # 1. 验证
        validator = OrderValidator()
        valid, error = validator.validate_order(order_data)
        if not valid:
            result['error'] = error
            return result
        
        # 2. 计算金额
        items = order_data['items']
        total = calculate_total(items)
        
        # 3. 应用折扣
        discount = order_data.get('discount_code')
        total = apply_discount(total, discount)
        
        # 4. 计算运费
        province = order_data.get('province')
        is_vip = order_data.get('is_vip', False)
        shipping = calculate_shipping(total, province, is_vip)
        
        # 5. 返回结果
        result['success'] = True
        result['total'] = total
        result['shipping'] = shipping
        result['final'] = total + shipping
        result['order_id'] = order_data.get('order_id')
        
    except Exception as e:
        result['error'] = str(e)
    
    return result