from flask import Flask, render_template, request, redirect, session, url_for, flash, Response
from pymongo import MongoClient
from datetime import datetime
from functools import wraps
import os

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY")
mongo_uri = os.environ.get("MONGO_URI")

# Conexión a MongoDB
client = MongoClient(mongo_uri)
db = client["inventory_db"]
collection = db["items"]
users_collection = db["users"]
sales_collection = db["sales"]

@app.route('/')
def index():
    return redirect(url_for('login'))

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'username' not in session:
                flash('Debes iniciar sesión primero.')
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('No tienes permisos para acceder a esta página.')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']
        password = request.form['password']
        user_data = users_collection.find_one({"username": user, "password": password})
        
        if user_data:
            session['username'] = user
            session['role'] = user_data['role']
            print("Login exitoso. Redirigiendo a /dashboard")
            return redirect(url_for('dashboard'))
        else:
            print("credenciales invalidas")
            return "Credenciales inválidas"
        

    return render_template("login.html")

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if session['role'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    else:
        return redirect(url_for('employee_dashboard'))

@app.route('/admin/dashboard', methods=['GET', 'POST'])
@login_required(role='admin')
def admin_dashboard():
    query = {}

    # Obtener filtros del formulario
    if request.method == 'POST':
        employee = request.form.get('employee')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        if employee:
            query['employee'] = employee

        if start_date:
            query['date'] = {'$gte': datetime.strptime(start_date, '%Y-%m-%d')}
        if end_date:
            query.setdefault('date', {})
            query['date']['$lte'] = datetime.strptime(end_date, '%Y-%m-%d')
    if not query:
        sales = sales_collection.find().sort('date', -1).limit(10)
    else:
        # Si hay filtros, aplicar la búsqueda con los filtros proporcionados
        sales = sales_collection.find(query).sort('date', -1)
    products = collection.find()
    employees = sales_collection.distinct('employee')  # Lista única de empleados

    return render_template('admin_dashboard.html', products=products, sales=sales, employees=employees)

@app.route('/employee/dashboard')
@login_required(role='employee')
def employee_dashboard():
    products = list(collection.find())
    return render_template('employee_dashboard.html', products=products)

@app.route('/admin/add_product', methods=['GET', 'POST'])
@login_required(role='admin')
def add_product():
    if request.method == 'POST':
        name = request.form['name']
        price = float(request.form['price'])
        quantity = int(request.form['quantity'])
    
        existing_product = collection.find_one({'name': name})
        
        if existing_product:
            flash("El producto ya existe en la base de datos.")
            return redirect(url_for('admin_dashboard'))
        
        new_product = {
            "name": name,
            "price": price,
            "quantity": quantity
        }
        
        collection.insert_one(new_product)
        flash("Producto registrado correctamente")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/export_sales')
@login_required(role='admin')
def export_sales():
    sales = sales_collection.find().sort('date', -1)

    # Crear archivo CSV en memoria
    def generate():
        yield 'Fecha,Empleado,Producto,Cantidad,Precio,Total\n'
        for sale in sales:
            for product in sale['products']:
                total = product['quantity'] * product['price']
                yield f"{sale['date'].strftime('%Y-%m-%d %H:%M:%S')},{sale['employee']},{product['name']},{product['quantity']},{product['price']},{total}\n"

    return Response(generate(), mimetype='text/csv',
                    headers={"Content-Disposition": "attachment;filename=ventas.csv"})

@app.route('/admin/update_product', methods=['GET', 'POST'])
@login_required(role='admin')
def update_product():
    if request.method == 'POST':
        # Obtener el nombre del producto desde el formulario
        product_name = request.form['name']

        # Buscar el producto en la base de datos
        product = collection.find_one({"name": product_name})

        if not product:
            flash("Producto no encontrado.")
            return redirect(url_for('admin_dashboard'))

        # Obtener los nuevos valores del formulario
        new_quantity = int(request.form['quantity'])

        # Actualizar el producto en la base de datos
        collection.update_one(
            {'name': product_name},
            {'$set': {'quantity': new_quantity}}
        )
        flash("Producto actualizado exitosamente.")
        return redirect(url_for('admin_dashboard', product=product))

@app.route('/admin/delete_product/', methods=['GET', 'POST'])
@login_required(role='admin')
def delete_product():
    product_name = request.form['name']
    collection.delete_one({'name': product_name})

    return redirect(url_for('admin_dashboard'))

@app.route('/employee/sell_product', methods=['POST'])
@login_required(role='employee')
def sell_product():
    if request.method == 'POST':
        # Obtener los datos del formulario
        products_data = request.form.getlist('name[]')  # Asumimos que se envían como lista de productos
        quantities = request.form.getlist('quantity[]')
        
        total_cost = 0
        products_sold = []  # Lista de productos vendidos para almacenar la información

        # Iterar sobre los productos seleccionados
        for name, quantity in zip(products_data, quantities):
            quantity = int(quantity)
            product = collection.find_one({'name': name})

            if product and product['quantity'] >= quantity:
                # Calcular el costo total de cada producto (puedes ajustar esto según cómo se maneje el precio)
                total_cost += product['price'] * quantity

                # Reducir la cantidad del producto en inventario
                collection.update_one({'name': name}, {'$inc': {'quantity': -quantity}})
                
                # Añadir el producto a la lista de productos vendidos
                products_sold.append({
                    'name': name,
                    'quantity': quantity,
                    'price': product['price']
                })
            else:
                flash(f"Producto {name} no disponible o cantidad insuficiente.")
                return redirect(url_for('employee_dashboard'))

        # Guardar la venta en la base de datos
        sale = {
            'products': products_sold,
            'total_cost': total_cost,
            'date': datetime.now(),  # Fecha y hora de la venta
            'employee': session['username']  # Nombre o ID del empleado que realizó la venta
        }

        # Insertar la venta en la colección 'sales'
        sales_collection.insert_one(sale)

        flash("Venta registrada exitosamente.")
        return redirect(url_for('employee_dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)