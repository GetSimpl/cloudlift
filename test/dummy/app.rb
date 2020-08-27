require 'sinatra'
require 'redis'

get '/' do
  redis_client = Redis.new(host: ENV['REDIS_HOST'])
  "This is dummy app. Label: #{ENV['LABEL']}. Redis PING: #{redis_client.ping}"
end

get '/elb-check' do
  "This is dummy app. Label: #{ENV['LABEL']}"
end